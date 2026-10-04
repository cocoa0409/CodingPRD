# Heavy Truck Uptime & Warranty API — Product Requirements Document

## 1. Introduction

Daimler Truck North America operates a 24/7 uptime center that coordinates fault response, dealer service, and warranty administration across a national fleet of heavy trucks. When a truck streams a fault code through its telematics unit, an uptime coordinator opens a case, dispatches the truck to a dealer's service bay, authorizes diagnostic time, and tracks the repair to completion. Afterward, a warranty administrator submits a claim, the failed part is returned to the supplier, and a supplier recovery is filed and settled. Overlaying this operational loop are fleet-level concerns: extended coverage contracts that need prorated adjustments on early cancellation, OEM campaigns and recalls that must reach a tracked completion threshold before they can be closed, and a fleet reliability score that decays as trucks pile up downtime, repeat repairs, and overdue campaign work.

This document specifies the REST API that backs those workflows. It is written for the engineers who will implement the service; the precise contract details — response envelope, pagination, error identifiers, OCC fields — appear in §2, while §3 walks each business process in narrative form with the cross-cutting rules scattered where they belong.

The API is mounted at the service root (`/`); there is no versioned prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level invariants every endpoint obeys.

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). If the role named by `X-User-Role` is not authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `FleetManager`, `UptimeCoordinator`, `DealerAdvisor`, `PartsManager`, `WarrantyAdmin`, and `SupplierManager`. Each role's relationship between the `X-User-ID` header and persisted entities is as follows:

- When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of the acting `Fleet`; ownership checks on any resource that references a `Fleet` compare the resource's `fleet_id` foreign key against `X-User-ID`.
- When `X-User-Role` is `DealerAdvisor`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` compare the resource's `dealer_id` foreign key against `X-User-ID`.
- When `X-User-Role` is `UptimeCoordinator`, `PartsManager`, `WarrantyAdmin`, or `SupplierManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

For entity-backed roles (`FleetManager`, `DealerAdvisor`), if the `X-User-ID` value does not resolve to an existing entity of the matching type, the request is rejected with `ERR_ACTOR_NOT_FOUND` (HTTP 404). This check runs only after the header-presence check and the role-authorization check, and only for entity-backed roles — opaque roles are never subject to it. The sole exception is `POST /fleets`: because no `Fleet` can exist before the first one is created, the `ERR_ACTOR_NOT_FOUND` check is skipped on that endpoint only (the header-presence and role checks still apply).

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

List endpoints paginate through `limit` and `offset` query parameters. `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order, with ties broken by `id` ascending. The `meta` object on list responses includes `limit`, `offset`, `total_count`, and `has_more` alongside the standard `api_request_id` and `api_request_timestamp`.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields:

- `id`: a server-minted UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version`: an integer starting at 1, incremented by 1 on every mutation of the resource.

Two resource families deviate from this convention. `FaultEvent` rows are append-only telematics events: they carry `id` and `created_at` only; `updated_at` and `version` are absent because the row is never mutated after creation (the only "state change" an event undergoes is moving from `UNLINKED` to `LINKED` or `DISMISSED`, which is recorded by rewriting the row's `event_status` field without bumping any version counter — there is none). `ReliabilityReport` rows are likewise append-only ops-run snapshots: they carry `id` and `created_at` only; `updated_at` and `version` are absent.

### 2.5. Logical Clock, Ops Runs, and Reporting Snapshots

The server maintains a logical clock that starts at 2026-09-01T00:00:00Z when the service boots. The clock is advanced through a dedicated test-driving endpoint that accepts a `to_iso8601` payload and is reachable by all six roles; the response reports the new `current_utc`. The endpoint accepts any valid ISO 8601 timestamp — it does not require the new value to be later than the current one. All time-window rules in this document — coverage expiration, part-return windows, campaign overdue sweeps, the 30-minute critical-fault response window, and the 90-day repeat-repair window — are evaluated against this logical clock, never against wall time.

A separate operations-run endpoint (administrative, `UptimeCoordinator` only) triggers a full sweep across every fleet. One ops run performs the following in order: (a) for each `OPEN` `CampaignCompletion` row whose parent campaign's `closes_on` is strictly earlier than the current clock — a row whose `closes_on` equals the current clock is *not* overdue — the owning fleet's `reliability_score` is decremented by 5, the parent campaign's `overdue_count` is recomputed as the count of `OPEN` rows past `closes_on`, and the repeat-repair window is re-evaluated for every truck so a `repeat_repair_flag` whose supporting cases have all slid out of the 90-day window is reset to `false` when no other fault code is still in repeat state on that truck; (b) any `ACTIVE` `CoverageContract` whose `ends_on` has been reached or passed, or whose truck's `odometer_miles` has reached or passed `max_miles`, transitions to `EXPIRED`; (c) any `PartReturn` still in `REQUESTED` whose return window has lapsed (current clock later than `created_at` plus `return_window_days`) transitions to `LATE_REJECTED`, and its claim's `recovery_status` transitions to `RECOVERY_DENIED`; (d) each fleet's `reliability_score` is recomputed from scratch from the full event history as an audit cross-check; and (e) a `ReliabilityReport` snapshot row is written per fleet carrying `ops_run_index`, `computed_at`, `trucks_in_service`, `trucks_down`, `total_downtime_hours`, `repeat_repair_truck_count`, `campaign_completion_pct`, and `reliability_score`. The response carries `ops_run_index` and `fleets_processed`; `ops_run_index` is 1 for the first ops run and increments by 1 per run. The campaign-completion percentage stored on a snapshot is the weighted mean of the `completion_pct` of all `OPEN` campaigns — campaigns are system-wide rather than fleet-scoped, so every `OPEN` campaign contributes to every fleet's snapshot — weighted by each campaign's count of non-`EXEMPTED` completion rows, rounded half-up to two decimal places (0.00 when no such rows exist).

### 2.6. Nested Resource Retrieval and Path Validation

Nested paths validate left to right. For a path under a fleet, the fleet identifier is resolved first (`ERR_FLEET_NOT_FOUND` on miss), then the truck within that fleet (`ERR_TRUCK_NOT_FOUND`), then the case within that truck (`ERR_CASE_NOT_FOUND`), then any deeper child — `ERR_WORK_ORDER_NOT_FOUND`, `ERR_PART_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PART_RETURN_NOT_FOUND`, or `ERR_RECOVERY_NOT_FOUND` as appropriate. Dealer-side paths resolve the dealer first (`ERR_DEALER_NOT_FOUND`), then the bay within that dealer (`ERR_BAY_NOT_FOUND`). Campaign paths resolve the campaign (`ERR_CAMPAIGN_NOT_FOUND`), then the completion row (`ERR_CAMPAIGN_COMPLETION_NOT_FOUND`). Coverage-contract paths under a truck resolve the contract (`ERR_COVERAGE_CONTRACT_NOT_FOUND`) after fleet and truck. Fault-event paths under a truck resolve the event (`ERR_FAULT_EVENT_NOT_FOUND`). Each is HTTP 404. There is no dedicated not-found error for reliability snapshots: reading a non-existent reliability-report id is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Beyond the nested forms, every entity also has a top-level cross-aggregate read endpoint so dashboards can list children by foreign-key query parameter without walking the URL hierarchy: trucks filterable by `fleet_id`, `truck_status`, `model_code`; cases by `fleet_id`, `truck_id`, `dealer_id`, `opened_from_fault_event_id`, `case_status`; work orders by `case_id`, `dealer_id`, `bay_id`, `work_order_status`; part orders by `case_id`, `part_order_status`, `expedite_decision`; claims by `case_id`, `submission_status`, `recovery_status`, `claim_type`; part returns by `claim_id`, `part_return_status`; recoveries by `claim_id`, `part_return_id`, `recovery_status`; coverage contracts by `truck_id`, `contract_status`, `contract_type`; fault events by `truck_id`, `event_status`, `severity`; campaign completions by `campaign_id`, `truck_id`, `case_id`, `completion_status`; bays by `dealer_id`, `bay_status`; reliability reports by `fleet_id` (and, on the fleet-nested variant, `from_ops_run_index` and `to_ops_run_index`); dealers by `region` and `dealer_status`. Single-resource top-level gets exist for each of these as well, addressed by the entity's own `id`.

### 2.7. Precision, Rounding, and Monetary Representation

All monetary amounts in this API are integer cents. Whenever a calculation produces a fractional cent, the result is rounded half-up to the nearest integer cent. Multiplication chains that produce intermediate fractional values round half-up to integer cents at the step where the scaffold names an intermediate rounding; the final `prorated_credit_cents` of coverage proration divides in rationals and rounds half-up exactly once at the end. Quantities expressed in hours (`downtime_hours`, `labor_hours_allowed`, `completion_pct`) are rounded half-up to two decimal places. Part weight totals — `quantity` times `part_weight_kg_per_unit` — are rounded half-up to one decimal place in kilograms, and the rounded total is what the freight tiers charge; a rounded total weight of 0.0 kg at expedite-evaluation time is rejected with `ERR_INVALID_REQUEST`.

### 2.8. Optimistic Concurrency Control

Three write endpoints carry an optimistic-concurrency contract; all other endpoints do not accept a version field.

- Scheduling a case requires the request to carry `expected_truck_version` equal to the truck's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). This catches the situation where another coordinator has just opened or scheduled a case on the same truck, legitimately advancing the truck's `version` (both case opening and scheduling write the truck row).
- Submitting a warranty claim requires `expected_case_version` equal to the case's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) — a prior claim submission, part-order creation, expedite re-evaluation, or other case write legitimately bumps `Case.version`, and a stale submitter must re-fetch before re-submitting.
- Closing a campaign requires `expected_campaign_version` equal to the campaign's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since another coordinator's exempt action — or a linked case closing and recomputing `completion_pct` — legitimately advances the campaign's `version`. (Scheduling a completion row does not recompute `completion_pct` and does not bump the campaign's `version`.)

In all three rules the request is rejected because the client's last-observed `version` no longer matches the server's current `version`; the framing is purely one of stale state, not of request timing.

### 2.9. Fleet Activity Gate and Truck Retirement Gate

A fleet whose `fleet_status` is not `ACTIVE` refuses every mutating operation under its hierarchy with `ERR_FLEET_NOT_ACTIVE` (HTTP 409); the fleet's own metadata update, suspend, and reactivate are not under the hierarchy and remain allowed on a non-`ACTIVE` fleet. A truck whose `truck_status` is `DECOMMISSIONED` refuses new case creation and new coverage-contract purchases with `ERR_TRUCK_DECOMMISSIONED` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Onboarding Fleets, Trucks, and the Dealer Network

A `FleetManager` creates a fleet by providing a `fleet_name` and a two-letter `home_region` code. New fleets are born `ACTIVE` with `reliability_score` initialized to 1000, `total_downtime_hours` at 0, and `open_case_count` at 0. Fleets can later be suspended and reactivated; suspending flips `fleet_status` to `SUSPENDED` and bumps the fleet's `version`, and reactivation returns it to `ACTIVE`. Suspending a fleet that is not `ACTIVE`, or reactivating one that is not `SUSPENDED`, is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Fleet metadata — `fleet_name` and `home_region` — can be updated, and each update increments the fleet's `version`.

Under a fleet, a `FleetManager` registers trucks with a 17-character `vin` (a `vin` of any other length is rejected with `ERR_INVALID_REQUEST`; the value must also be unique across all trucks — a duplicate is rejected with `ERR_DUPLICATE_IDENTIFIER`), a `model_code`, the `in_service_on` date the truck entered revenue service, an initial `odometer_miles` reading, and the base factory warranty boundaries `base_warranty_until_miles` and `base_warranty_until_on`. New trucks start with `truck_status` of `IN_SERVICE`, an `open_case_count` of 0, and a `repeat_repair_flag` of `false`. A truck's odometer may be updated over its life, but `odometer_miles` must be monotonically non-decreasing: an update carrying a value lower than the current one is rejected with `ERR_ODOMETER_REGRESSION` (HTTP 422). A truck's `model_code` may be updated through the same endpoint. A successful odometer update increments the truck's `version`.

On the dealer side, a `FleetManager` onboards a `Dealer` with a `dealer_name`, the `region` code the dealer operates in, and a posted `hourly_labor_rate_cents` that must be greater than zero. New dealers are born `ACTIVE` with `bay_count` and `active_case_count` both at 0. `active_case_count` is a read-only derived counter of that dealer's cases in `SCHEDULED`, `IN_SERVICE`, or `AWAITING_PART`, recomputed as cases are scheduled, started, closed, or cancelled. A `DealerAdvisor` then creates service bays at that dealer by supplying a dealer-local `bay_code` — the ownership rule of §2.1 applies to this create, so a `DealerAdvisor` whose `X-User-ID` is not the target dealer's `id` is rejected with `ERR_FORBIDDEN_FOR_ROLE`; new bays start with `bay_status` of `AVAILABLE` and increment the dealer's `bay_count` (which counts every non-`DECOMMISSIONED` bay at the dealer).

When a truck reaches end of life, a `FleetManager` decommissions it — but only when the truck's `open_case_count` is zero; otherwise the transition is refused with `ERR_INVALID_STATE_TRANSITION`. Decommissioning an already-`DECOMMISSIONED` truck is likewise rejected with `ERR_INVALID_STATE_TRANSITION`. Decommissioning flips `truck_status` to `DECOMMISSIONED` and fans out two cascades: every `ACTIVE` `CoverageContract` on the truck transitions to `CANCELLED`, the coverage proration calculation runs, and the resulting `prorated_credit_cents` is credited to the fleet's ledger; and every `OPEN` `CampaignCompletion` row pointing at that truck transitions to `EXEMPTED` with its `exemption_reason` set to the literal string `TRUCK_DECOMMISSIONED`.

### 3.2. Fault Ingestion and Case Opening

A `UptimeCoordinator` ingests telematics fault events on a truck, supplying `fault_code` (SPN/FMI-style, e.g. `SPN3216_FMI4`), `severity` (one of `INFO`, `WARNING`, `CRITICAL`), `recommended_action` (one of `MONITOR`, `SCHEDULE_SERVICE`, `STOP_IMMEDIATELY`), and `occurred_at`, which must be no later than the server's current clock — a future `occurred_at` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). New fault events are born `UNLINKED`. An `UNLINKED` event may be dismissed by a `UptimeCoordinator`, moving it to `DISMISSED`; both `LINKED` and `DISMISSED` are terminal.

Opening a case is the uptime center's response to a fault. A `UptimeCoordinator` supplies the case's `fault_code` and, optionally, a `fault_event_id` linking back to a specific fault event. When `fault_event_id` is present, the referenced event must still be `UNLINKED` — linking an already-`LINKED` or `DISMISSED` event is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409) — and when the referenced event had `severity` of `CRITICAL` together with `recommended_action` of `STOP_IMMEDIATELY`, the case must be opened within 30 minutes of the event's `occurred_at` — that is, `occurred_at` must be no earlier than the current clock minus 30 minutes; otherwise the create is rejected with `ERR_CRITICAL_FAULT_WINDOW_LAPSED` (HTTP 422). On success, the case is created in `OPEN` status with `opened_at` set to the server's clock, `closed_at` null, `downtime_hours` at 0.00, `diagnostic_minutes_authorized` at 0, `expedite_count` at 0, and `opened_from_fault_event_id` recorded when applicable. The truck's `open_case_count` and the fleet's `open_case_count` are each incremented. When the case was opened from a fault event, the event transitions `UNLINKED` → `LINKED`, and the case's `severity_at_open` snapshots the event's `severity` (it stays null when the case is opened without a fault event). The case also denormalizes `fleet_id` from its truck's owning fleet for reporting, consistent with the truck's `fleet_id`. The case's `dealer_id` stays null until scheduling assigns one.

A fleet's `open_case_count` and a truck's `open_case_count` count cases in any of `OPEN`, `TRIAGE`, `SCHEDULED`, `IN_SERVICE`, `AWAITING_PART`, or `PENDING_CLOSE` — both are read-only and recomputed synchronously as cases open and resolve.

### 3.3. Triage, Scheduling, and Bay Allocation

An `OPEN` case is triaged by a `UptimeCoordinator`, advancing it to `TRIAGE` and incrementing the case's `version`. From `TRIAGE`, the coordinator schedules the case onto a specific dealer's bay by supplying `dealer_id`, `bay_id`, `scheduled_start_at`, `scheduled_end_at`, the OCC field `expected_truck_version`, and an optional `allow_cross_region` flag.

Scheduling enforces its business checks in order: first the OCC stale-version check of §2.8; then the window-validity check — `scheduled_end_at` must be strictly later than `scheduled_start_at` and the duration at least 30 minutes, with a violation rejected with `ERR_INVALID_WORK_ORDER_WINDOW` (HTTP 422) — the same rule applies if the work order window is later revised through the work-order update path; then the bay-time check — the bay must be `AVAILABLE` for the requested window, meaning a bay whose `bay_status` is `DOWN` or `DECOMMISSIONED` is never available, while a bay in `RESERVED` or `IN_USE` remains available for non-overlapping windows (touching intervals, where one window's end equals the other's start, do not overlap), and no other `AUTHORIZED` or `IN_PROGRESS` work order on the same bay may have an overlapping `[start, end)` interval with the requested one; a conflict is rejected with `ERR_BAY_TIME_CONFLICT` (HTTP 409). Last comes the dealer-availability check — the dealer's `dealer_status` must be `ACTIVE`, and the dealer's `region` must match the fleet's `home_region` unless the request sets `allow_cross_region` to true; a suspended dealer or a cross-region dispatch without that flag is rejected with `ERR_DEALER_NOT_AVAILABLE` (HTTP 409).

On success the case moves `TRIAGE` → `SCHEDULED`: `Case.dealer_id` is set, a `DRAFT` `WorkOrder` is created linking the case to the dealer and the bay (with `case_id`, `dealer_id`, `bay_id`, `scheduled_start_at`, and `scheduled_end_at` recorded), the bay's `bay_status` flips to `RESERVED`, and both the truck's `version` and the case's `version` increment (the truck bump is the OCC write that later scheduling attempts are checked against). The schedule response returns the updated case object, not the new work order.

### 3.4. Authorizing Diagnostic Time and Running the Repair

A `DRAFT` work order becomes `AUTHORIZED` when a `UptimeCoordinator` authorizes diagnostic time on it, supplying `diagnostic_minutes_authorized` — which must be greater than zero for this transition; a non-positive value is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — while the case is in `SCHEDULED`. The case's running `diagnostic_minutes_authorized` total (a read-only sum across its linked work orders) is incremented by the authorized amount. Cancelling a work order from `DRAFT` or `AUTHORIZED` flips it to `CANCELLED`, releases the bay back to `AVAILABLE` if it was `RESERVED` for that work order, and decrements the case's `diagnostic_minutes_authorized` by this work order's authorized amount.

Once the work order is `AUTHORIZED` and its bay is `RESERVED` for that work order, a `DealerAdvisor` starts service: when several `AUTHORIZED` work orders exist on the case, the earliest-created one is started; the case moves `SCHEDULED` → `IN_SERVICE`, the work order moves `AUTHORIZED` → `IN_PROGRESS`, the bay moves `RESERVED` → `IN_USE`, and the truck's `truck_status` flips to `DOWN` (a truck already `DOWN` from another case stays `DOWN`). The response returns the updated case object. The fleet's `open_case_count` is unchanged — the case is still open.

When the repair finishes, the `DealerAdvisor` completes the work order by supplying `labor_minutes_actual` (zero or more) and a `repair_outcome` of `FIXED`, `NOT_FIXED`, or `PARTIAL`. Completion moves the work order `IN_PROGRESS` → `COMPLETED`. If the outcome is anything other than `FIXED`, the repeat-repair window (§3.9) is recomputed for the truck.

### 3.5. Parts Ordering and the Expedite Decision

A `PartsManager` creates a part order against a case that is in `IN_SERVICE` (a create attempted when the case is not in `IN_SERVICE` is rejected with `ERR_CASE_NOT_AWAITING_PART`, HTTP 409). The request carries `part_number`, `quantity` (at least 1), `part_weight_kg_per_unit` (zero or more — a negative value is rejected with `ERR_INVALID_REQUEST`), and `part_cost_cents` (zero or more). The new part order is born `PENDING` with `expedite_decision` of `PENDING_EVAL`, `expedite_cost_cents` and `downtime_cost_cents` both at 0. As a side effect, the case moves `IN_SERVICE` → `AWAITING_PART` (the truck remains `DOWN`).

The `PartsManager` then runs the expedite evaluation on the part order, supplying `dealer_repair_hours_est`, `downtime_rate_cents_per_hour`, and `distance_band` (one of `INTRA_REGION`, `CROSS_COUNTRY`, `INTERNATIONAL`). Freight pricing is tiered by band: `INTRA_REGION` charges a base of 15000 cents plus 300 cents per kilogram; `CROSS_COUNTRY` charges a base of 45000 cents plus 900 cents per kilogram; `INTERNATIONAL` charges a base of 150000 cents plus 3000 cents per kilogram. Total weight in kilograms is the `quantity` multiplied by `part_weight_kg_per_unit`, rounded half-up to one decimal place; a zero-weight evaluation is rejected with `ERR_INVALID_REQUEST`. The overnight freight cost is the band's base plus its per-kilogram rate multiplied by the total weight; the standard freight cost is 40 percent of the overnight cost, rounded half-up to integer cents.

With freight priced, the decision algorithm computes an estimated downtime cost as `dealer_repair_hours_est` multiplied by `downtime_rate_cents_per_hour`, rounded half-up to integer cents — this value is stored on the part order's `downtime_cost_cents`. The overnight gain is the downtime cost minus the overnight freight cost. The standard gain is 60 percent of the downtime cost, rounded half-up to integer cents, minus the standard freight cost. If the overnight gain is zero or positive and is also at least as large as the standard gain, the decision is `EXPEDITE_OVERNIGHT` and `expedite_cost_cents` records the overnight cost — note the tie-breaking rule: when overnight gain equals standard gain, overnight wins. Otherwise, if the standard gain is zero or positive, the decision is `EXPEDITE_STANDARD` and `expedite_cost_cents` records the standard cost. Otherwise the decision is `DENIED` and `expedite_cost_cents` stays at 0. When the decision lands on `EXPEDITE_OVERNIGHT`, the case's `expedite_count` increments. The evaluation may be re-run on the same part order; `expedite_count` tracks transitions — entering `EXPEDITE_OVERNIGHT` from any other decision increments it, and leaving `EXPEDITE_OVERNIGHT` for another decision decrements it (never below zero).

From `PENDING`, a part order may be cancelled by a `PartsManager` (or by the case-cancel cascade); if the order's `expedite_decision` was `EXPEDITE_OVERNIGHT`, the case's `expedite_count` decrements (never below zero). A `PENDING` order whose `expedite_decision` is `EXPEDITE_OVERNIGHT` or `EXPEDITE_STANDARD` may be marked shipped by a `PartsManager`, moving to `SHIPPED`. A `DealerAdvisor` marks a `SHIPPED` order received (`RECEIVED`) and, while the case is in `IN_SERVICE` or `AWAITING_PART`, marks a `RECEIVED` order installed (`INSTALLED`). When the last non-terminal part order on the case reaches `INSTALLED` or `CANCELLED`, the case moves `AWAITING_PART` → `IN_SERVICE` automatically.

### 3.6. Warranty Claims: Submission, Review, and Adjudication

A `WarrantyAdmin` creates a warranty claim against a case by supplying `claim_type` (one of `BASE_WARRANTY`, `EXTENDED_COVERAGE`, `CAMPAIGN`, `GOODWILL`), `labor_minutes_claimed`, and `parts_claimed_cents` (zero or more). The new claim starts with `submission_status` of `DRAFT` and `recovery_status` of `NOT_INITIATED`; its `labor_rate_cents_per_hour` is snapshotted from the case's dealer at creation and is never recomputed, even if the dealer's posted rate later changes — when the case has no dealer assigned yet, the snapshot is 0. `recovery_amount_cents` starts at 0.

Submitting a `DRAFT` claim requires the case to be in `IN_SERVICE`, `AWAITING_PART`, `PENDING_CLOSE`, or `CLOSED` and requires the OCC field `expected_case_version` matching the case's current `version` (§2.8). At submission the labor time standard runs: each fault code has a base-hour allowance — `SPN3216_FMI4` (aftertreatment doser) allows 4.0 hours, `SPN3226_FMI4` (DOC pressure) allows 3.5 hours, `SPN168_FMI4` (battery potential) allows 2.0 hours, and any other fault code allows 2.5 hours — which is then scaled by a claim-type multiplier: `BASE_WARRANTY` at 1.0, `CAMPAIGN` at 0.9, `EXTENDED_COVERAGE` at 1.1, and `GOODWILL` at 0.0 (goodwill claims never reimburse labor). The resulting `labor_hours_allowed` is the base hours multiplied by the multiplier, rounded half-up to two decimal places. The requested `labor_minutes_claimed` must be no more than `labor_hours_allowed` times 60; the comparison is inclusive, so a claim equal to exactly that many minutes succeeds while one minute more fails with `ERR_LABOR_MINUTES_EXCEED_STANDARD` (HTTP 422). `labor_amount_allowed_cents` is `labor_hours_allowed` multiplied by the snapshotted `labor_rate_cents_per_hour`, rounded per the integer-cent rounding rule.

The parts allowance runs in the same submission step. The coverage fraction depends on `claim_type`: for `BASE_WARRANTY`, the parts cap is 100 percent when the truck's `odometer_miles` is no greater than `base_warranty_until_miles`, and 0 percent once the truck has passed that odometer limit. For `CAMPAIGN`, the parts cap is always 100 percent. For `EXTENDED_COVERAGE`, the cap is the coverage-proration fraction — the prorated credit the truck's `ACTIVE` coverage contract would yield if cancelled at the current clock (§3.10), divided by its `premium_cents` — clamped to a maximum of 100 percent; when the truck has no `ACTIVE` contract, the cap is 0 percent. For `GOODWILL`, the cap is 50 percent. `parts_amount_allowed_cents` is `parts_claimed_cents` multiplied by the cap fraction, rounded half-up to integer cents. A successful submission moves `submission_status` to `SUBMITTED` and increments the case's `version`.

From `SUBMITTED`, a `WarrantyAdmin` begins review, moving the claim to `UNDER_REVIEW`. From `UNDER_REVIEW` there are three sibling adjudication outcomes, all performed by a `WarrantyAdmin`:

- **Full approval.** The claim moves to `APPROVED`. If `claim_type` is `BASE_WARRANTY` or `CAMPAIGN`, the claim's `recovery_status` moves `NOT_INITIATED` → `PART_RETURN_REQUESTED` and a `PartReturn` row is created in `REQUESTED` status against the claim, with `part_number` taken from an installed part order on the case (null when no part order is installed) and `return_window_days` snapshotted — 30 days for `BASE_WARRANTY`, 45 days otherwise. The return's `shipped_at` and `received_at` start null.
- **Partial approval.** When the admin supplies `partial_labor_amount_allowed_cents` or `partial_parts_amount_allowed_cents` and the supplied value is lower than the corresponding computed allowance, the claim moves to `PARTIAL_APPROVED` with the allowances reduced to the supplied values; the reductions are recorded as deltas. A supplied value equal to or greater than the computed allowance is ignored, and when neither supplied value is lower the claim is fully `APPROVED` instead. The `BASE_WARRANTY`/`CAMPAIGN` part-return creation described for full approval applies to partial approval as well. This path uses the same labor-time-standard formula but only ever adjusts downward.
- **Denial.** The claim moves to `DENIED`. If a `PartReturn` was already in `REQUESTED` for this claim, that return is moved to `LATE_REJECTED` and the claim's `recovery_status` is set to `RECOVERY_DENIED`.

A case cannot be closed while any of its claims is in `SUBMITTED` or `UNDER_REVIEW`: such a close is rejected with `ERR_CASE_HAS_OPEN_CLAIM` (HTTP 409).

### 3.7. Failed-Part Return and Supplier Recovery

The part-return lifecycle is driven jointly by the dealer and the supplier side. A `DealerAdvisor` ships the failed part back: the return moves `REQUESTED` → `IN_TRANSIT`, its `shipped_at` is stamped, and the parent claim's `recovery_status` moves `PART_RETURN_REQUESTED` → `PART_IN_TRANSIT`. The ship is only allowed while the current clock is no later than the return's `created_at` plus its `return_window_days`; a late ship attempt is rejected with `ERR_RETURN_WINDOW_LAPSED` (HTTP 422). Independently, if the ops run finds a return still in `REQUESTED` whose window has lapsed, the return is moved to `LATE_REJECTED` and the claim's `recovery_status` to `RECOVERY_DENIED`.

A `SupplierManager` then marks the return received: the return moves `IN_TRANSIT` → `RECEIVED` with `received_at` stamped, and the claim's `recovery_status` moves `PART_IN_TRANSIT` → `PART_RECEIVED`. Inspection follows, with the `SupplierManager` supplying `inspection_disposition`. A disposition of `OK` moves the return to `INSPECTED_OK`. A disposition of `FAILED` moves the return to `INSPECTED_FAILED` and drives the claim's `recovery_status` to `RECOVERY_DENIED`.

Filing a supplier recovery requires the linked part return to be in `INSPECTED_OK`; the `SupplierManager` supplies `part_return_id`, `supplier_id`, and `claimed_amount_cents` (zero or more). The claimed amount must not exceed the claim's `parts_amount_allowed_cents`, and the return's status must be `INSPECTED_OK` — violations are rejected with `ERR_RECOVERY_CLAIM_EXCEEDS_ALLOWANCE` (HTTP 422). On success a `SupplierRecovery` is created in `FILED` status with `paid_amount_cents` at 0, and the claim's `recovery_status` advances to `RECOVERY_FILED`. There is at most one recovery per part return; a second filing against the same part return is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409).

A filed recovery can be disputed (`FILED` → `UNDER_DISPUTE`) and later refiled (`UNDER_DISPUTE` → `FILED`), cycling as often as the parties need. From either `FILED` or `UNDER_DISPUTE` the `SupplierManager` marks the recovery paid by supplying `paid_amount_cents`. The paid amount must not exceed `claimed_amount_cents` — a larger payment is rejected with `ERR_RECOVERY_OVERPAID` (HTTP 422). The paid amount first offsets the OEM's recorded `parts_amount_allowed_cents` on the claim; the claim's `recovery_amount_cents` is then incremented by the paid amount, the recovery's `paid_amount_cents` is set, the recovery moves to `PAID`, and the claim's `recovery_status` advances to `RECOVERY_PAID`. Alternatively, a recovery in `FILED` or `UNDER_DISPUTE` may be denied outright, moving to `DENIED` and pushing the claim's `recovery_status` to `RECOVERY_DENIED`.

### 3.8. Case Close-Out, Cancellation, and Reopen

When the physical work is done, a `DealerAdvisor` requests case close. The transition `IN_SERVICE` → `PENDING_CLOSE` requires every work order on the case to be `COMPLETED` or `CANCELLED` and every part order on the case to be `INSTALLED` or `CANCELLED`. A `PENDING_CLOSE` case can be sent back to `IN_SERVICE` by a `UptimeCoordinator` — this is the reopen path used when warranty review kicks a case back — and the bay returns to `IN_USE` if it had already been released to `AVAILABLE`.

Final close is performed by a `UptimeCoordinator`. Provided no claim on the case is in `SUBMITTED` or `UNDER_REVIEW`, the case moves to `CLOSED`: `closed_at` is stamped with the server clock; `downtime_hours` is computed as the elapsed time from `opened_at` to `closed_at`, converted to hours and rounded half-up to two decimal places (a 30-minute closure records 0.50; a 1-minute closure records 0.02; the value is never negative); the fleet's `total_downtime_hours` is incremented by that amount; the bay returns to `AVAILABLE` if it was still `IN_USE` for this case; the truck's and fleet's `open_case_count` are each decremented; and if the truck has no remaining open cases, its `truck_status` returns to `IN_SERVICE`. If the case's downtime exceeded 24.0 hours — strictly greater than, not equal to — the fleet's `reliability_score` drops by 10. The repeat-repair window (§3.9) is also re-evaluated for the truck and the case's fault code at close. Closing also completes campaign work: any linked `CampaignCompletion` in `SCHEDULED` moves to `COMPLETED` and the campaign's `completion_pct` is recomputed.

A case in `OPEN`, `TRIAGE`, or `SCHEDULED` may instead be cancelled by a `UptimeCoordinator`. Cancellation moves the case to `CANCELLED` (with `closed_at` staying null), moves every `DRAFT` work order on the case to `CANCELLED` and releases each such work order's bay back to `AVAILABLE` if it was `RESERVED`, moves every `PENDING` part order on the case to `CANCELLED` (decrementing the case's `expedite_count`, never below zero, for each whose `expedite_decision` was `EXPEDITE_OVERNIGHT`), and decrements both the truck's and the fleet's `open_case_count`. Work orders already past `DRAFT` (for example an `AUTHORIZED` work order on a `SCHEDULED` case) are left untouched by the cancellation. A `SCHEDULED` campaign completion whose linked case is cancelled reverts from `SCHEDULED` back to `OPEN` and its `case_id` is cleared.

### 3.9. Repeat-Repair Detection and the Fleet Reliability Score

The system tracks repeat repairs on a rolling 90-day window per truck per fault code. For a given truck and `fault_code`, the window count is the number of case rows on that truck carrying that fault code whose `opened_at` is within the last 90 days — the boundary is inclusive, so a case opened exactly 90 days ago still counts — and whose `case_status` is not `CANCELLED`. When that count reaches 3, the truck's `repeat_repair_flag` becomes `true` and the fleet's `reliability_score` is decremented by 25; the penalty is idempotent per (truck, fault code) pair until the window slides. When window slide at an ops run drops the count below 3, the flag is cleared — provided no other fault code on the same truck is still in repeat state.

The fleet's `reliability_score` starts at 1000 and is decremented by four kinds of events: a case closing with `downtime_hours` strictly greater than 24.0 subtracts 10; a work order completing with `repair_outcome` of `NOT_FIXED` subtracts 15; a repeat-repair threshold crossing subtracts 25 as above; and each `OPEN` `CampaignCompletion` row found past its campaign's `closes_on` at an ops run subtracts 5 per row per run. The score has a floor of 0 — further penalties clamp at 0 rather than driving it negative. Penalties apply exactly once per triggering event; the ops run's snapshot variant recomputes the score from the full event history as an audit cross-check.

### 3.10. Extended Coverage Contracts and Proration

A `FleetManager` purchases an extended coverage contract for a truck by supplying `contract_type` (one of `EXTENDED_POWERTRAIN`, `EXTENDED_AFTERTREATMENT`, `EXTENDED_FULL`), `starts_on`, `ends_on`, `max_miles`, and `premium_cents`. The window must be valid: `starts_on` strictly earlier than `ends_on`, and `starts_on` no earlier than the truck's `in_service_on`; violations are rejected with `ERR_INVALID_COVERAGE_WINDOW` (HTTP 422). New contracts are born `ACTIVE` with `prorated_credit_cents` at 0.

A contract expires automatically at the next ops run once the current clock reaches or passes `ends_on`, or once the truck's `odometer_miles` reaches or passes `max_miles`; expiry itself records no credit — `prorated_credit_cents` stays at 0 for an `EXPIRED` contract. A `FleetManager` may also cancel an `ACTIVE` contract early (cancelling a contract in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`, HTTP 409). Either way the coverage proration determines the credit, but cancellation is where the credit is actually computed and recorded: two proration bases are computed and the one yielding the smaller credit (most favorable to the OEM) is used. The time-based base takes the contract's total span in whole days (floor of `ends_on` minus `starts_on`), the elapsed whole days from `starts_on` to the cancellation instant (floored and clamped into the range from zero to the total days), and multiplies the `premium_cents` by the fraction of days remaining. The mileage-based base takes `max_miles` as the total miles, computes used miles as the truck's current `odometer_miles` minus the truck's odometer reading at contract start (clamped into the range from zero to the total miles), and multiplies the `premium_cents` by the fraction of miles remaining. The `prorated_credit_cents` is the smaller of the two credits, rounded half-up to integer cents, with the division carried in rationals and rounded once at the end. Two boundaries anchor the formula: cancelling at the exact `starts_on` instant yields the full `premium_cents` back; a truck that has reached `max_miles` yields zero. The credit is applied to the fleet's ledger. The same proration, evaluated lazily, supplies the cap fraction for `EXTENDED_COVERAGE` claims (§3.6).

### 3.11. Campaigns and Fleet-Wide Completion Tracking

A `UptimeCoordinator` opens a campaign by supplying a unique `campaign_code` (a duplicate is rejected with `ERR_DUPLICATE_IDENTIFIER`), a `campaign_kind` of `RECALL` or `SERVICE_CAMPAIGN`, a non-empty `affected_model_codes` array of truck model codes, the `fault_code` the campaign addresses, and the `opens_on` / `closes_on` window — `closes_on` must be strictly later than `opens_on` and the affected-model list must be a non-empty array of strings, else the create is rejected with `ERR_INVALID_CAMPAIGN_WINDOW` (HTTP 422). The campaign's `campaign_status` is born `OPEN`, with `completion_pct` at 0 and `overdue_count` at 0. For every truck whose `model_code` appears in `affected_model_codes` and whose `in_service_on` is no later than `closes_on`, a `CampaignCompletion` row is created in `OPEN` status with `case_id` null.

A `UptimeCoordinator` schedules a completion row by linking it to a `case_id`; the referenced case must exist (`ERR_CASE_NOT_FOUND`, HTTP 404, on a miss). The linked case's `fault_code` must equal the campaign's `fault_code`, the case's truck must be the completion row's truck, and the case must be in `TRIAGE`, `SCHEDULED`, `IN_SERVICE`, or `AWAITING_PART`; a mismatched link is rejected with `ERR_CAMPAIGN_COMPLETION_MISMATCH` (HTTP 409). On success the row moves `OPEN` → `SCHEDULED` and the `case_id` is stored. When the linked case later closes, the row moves `SCHEDULED` → `COMPLETED` and the campaign's `completion_pct` is recomputed. A row in `OPEN` may instead be exempted by a `UptimeCoordinator` supplying an `exemption_reason` — the reason is required for that transition — moving the row to `EXEMPTED` and recomputing `completion_pct`. The truck-decommission cascade also exempts rows automatically with `exemption_reason` of `TRUCK_DECOMMISSIONED` (§3.1).

The campaign's `completion_pct` is the percentage of its completion rows in `COMPLETED`, computed over rows whose `completion_status` is not `EXEMPTED` — exempted rows are excluded from both numerator and denominator — rounded half-up to two decimal places. A campaign whose entire scope is exempted therefore reports 0.00, never 100.00.

A `UptimeCoordinator` closes a campaign by supplying `expected_campaign_version` (§2.8). Closure is permitted once `completion_pct` reaches at least 95.00, or once the current clock is strictly later than `closes_on` plus 90 days; an attempt before either condition holds is rejected with `ERR_CAMPAIGN_NOT_CLOSABLE` (HTTP 409). Successful closure moves the campaign to `CLOSED`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions — return `200 OK`. List and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin, SupplierManager |
| POST | `/_ops/run` | Trigger an ops run: overdue-campaign sweep, coverage expiry, late-return rejection, reliability snapshot | UptimeCoordinator |
| POST | `/fleets` | Create a fleet | FleetManager |
| GET | `/fleets` | List fleets | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin, SupplierManager |
| GET | `/fleets/{fleetId}` | Get one fleet | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin, SupplierManager |
| PUT | `/fleets/{fleetId}` | Update fleet metadata | FleetManager |
| POST | `/fleets/{fleetId}/suspend` | Suspend a fleet | FleetManager |
| POST | `/fleets/{fleetId}/reactivate` | Reactivate a suspended fleet | FleetManager |
| POST | `/fleets/{fleetId}/trucks` | Register a truck | FleetManager |
| GET | `/fleets/{fleetId}/trucks` | List trucks in a fleet | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin |
| GET | `/fleets/{fleetId}/trucks/{truckId}` | Get one truck | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin, SupplierManager |
| PUT | `/fleets/{fleetId}/trucks/{truckId}` | Update truck odometer / metadata | FleetManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/decommission` | Decommission a truck | FleetManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/fault-events` | Ingest a telematics fault event | UptimeCoordinator |
| GET | `/fleets/{fleetId}/trucks/{truckId}/fault-events` | List fault events for a truck | UptimeCoordinator, FleetManager, DealerAdvisor, WarrantyAdmin |
| POST | `/fleets/{fleetId}/trucks/{truckId}/fault-events/{faultEventId}/dismiss` | Dismiss an UNLINKED fault event | UptimeCoordinator |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases` | Open a case, optionally linked to a fault event | UptimeCoordinator |
| GET | `/fleets/{fleetId}/trucks/{truckId}/cases` | List cases for a truck | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin, SupplierManager |
| GET | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}` | Get one case | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin, SupplierManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/triage` | Triage an OPEN case | UptimeCoordinator |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/schedule` | Schedule a TRIAGE case onto a dealer bay | UptimeCoordinator |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/start-service` | Start service on a SCHEDULED case | DealerAdvisor |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/request-close` | Move an IN_SERVICE case to PENDING_CLOSE | DealerAdvisor |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/reopen-service` | Reopen a PENDING_CLOSE case back to IN_SERVICE | UptimeCoordinator |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/close` | Close a PENDING_CLOSE case | UptimeCoordinator |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/cancel` | Cancel an OPEN, TRIAGE, or SCHEDULED case | UptimeCoordinator |
| GET | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/work-orders` | List work orders for a case | UptimeCoordinator, FleetManager, DealerAdvisor, WarrantyAdmin |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/work-orders/{workOrderId}/authorize` | Authorize diagnostic time on a DRAFT work order | UptimeCoordinator |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/work-orders/{workOrderId}/complete` | Complete an IN_PROGRESS work order | DealerAdvisor |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/work-orders/{workOrderId}/cancel` | Cancel a DRAFT or AUTHORIZED work order | UptimeCoordinator |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/part-orders` | Create a part order against an IN_SERVICE case | PartsManager |
| GET | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/part-orders` | List part orders for a case | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/part-orders/{partOrderId}/evaluate-expedite` | Run the expedite decision algorithm | PartsManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/part-orders/{partOrderId}/ship` | Mark a part order shipped | PartsManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/part-orders/{partOrderId}/receive` | Mark a part order received at the dealer | DealerAdvisor |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/part-orders/{partOrderId}/install` | Mark a part order installed on the truck | DealerAdvisor |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/part-orders/{partOrderId}/cancel` | Cancel a PENDING part order | PartsManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims` | Create a warranty claim against a case | WarrantyAdmin |
| GET | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims` | List claims for a case | FleetManager, UptimeCoordinator, WarrantyAdmin, SupplierManager |
| GET | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}` | Get one claim | FleetManager, UptimeCoordinator, DealerAdvisor, WarrantyAdmin, SupplierManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/submit` | Submit a DRAFT claim (computes allowances; OCC against the case) | WarrantyAdmin |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/begin-review` | Move a claim from SUBMITTED to UNDER_REVIEW | WarrantyAdmin |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/approve` | Approve an UNDER_REVIEW claim, optionally partially | WarrantyAdmin |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/deny` | Deny an UNDER_REVIEW claim | WarrantyAdmin |
| GET | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/part-returns` | List part returns for a claim | DealerAdvisor, WarrantyAdmin, SupplierManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/part-returns/{partReturnId}/ship` | Mark the failed part shipped back to the supplier | DealerAdvisor |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/part-returns/{partReturnId}/receive` | Mark the failed part received at the supplier | SupplierManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/part-returns/{partReturnId}/inspect` | Inspect the received part | SupplierManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/recoveries` | File a supplier recovery against an INSPECTED_OK part return | SupplierManager |
| GET | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/recoveries` | List supplier recoveries for a claim | WarrantyAdmin, SupplierManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/recoveries/{recoveryId}/dispute` | Mark a recovery disputed | SupplierManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/recoveries/{recoveryId}/refile` | Refile a disputed recovery | SupplierManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/recoveries/{recoveryId}/mark-paid` | Mark a recovery paid | SupplierManager |
| POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/recoveries/{recoveryId}/deny` | Deny a recovery | SupplierManager |
| POST | `/dealers` | Onboard a dealer | FleetManager |
| GET | `/dealers` | List dealers | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager |
| GET | `/dealers/{dealerId}` | Get one dealer | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin |
| POST | `/dealers/{dealerId}/bays` | Create a service bay at a dealer | DealerAdvisor |
| GET | `/dealers/{dealerId}/bays` | List bays at a dealer | UptimeCoordinator, DealerAdvisor, PartsManager |
| POST | `/dealers/{dealerId}/bays/{bayId}/mark-down` | Mark a bay down | DealerAdvisor |
| POST | `/dealers/{dealerId}/bays/{bayId}/mark-available` | Bring a down bay back | DealerAdvisor |
| POST | `/fleets/{fleetId}/trucks/{truckId}/coverage-contracts` | Purchase an extended coverage contract | FleetManager |
| GET | `/fleets/{fleetId}/trucks/{truckId}/coverage-contracts` | List coverage contracts for a truck | FleetManager, WarrantyAdmin |
| POST | `/fleets/{fleetId}/trucks/{truckId}/coverage-contracts/{contractId}/cancel` | Cancel an ACTIVE coverage contract early | FleetManager |
| POST | `/campaigns` | Open a campaign | UptimeCoordinator |
| GET | `/campaigns` | List campaigns | FleetManager, UptimeCoordinator, WarrantyAdmin |
| GET | `/campaigns/{campaignId}` | Get one campaign | FleetManager, UptimeCoordinator, WarrantyAdmin, SupplierManager |
| POST | `/campaigns/{campaignId}/close` | Close a campaign (OCC against the campaign) | UptimeCoordinator |
| GET | `/campaigns/{campaignId}/completions` | List completion rows for a campaign | FleetManager, UptimeCoordinator, WarrantyAdmin |
| POST | `/campaigns/{campaignId}/completions/{completionId}/schedule` | Link a completion row to a case | UptimeCoordinator |
| POST | `/campaigns/{campaignId}/completions/{completionId}/exempt` | Exempt a completion row | UptimeCoordinator |
| GET | `/fleets/{fleetId}/reliability-reports` | List reliability snapshots for a fleet | FleetManager, UptimeCoordinator, WarrantyAdmin |
| GET | `/trucks/{truckId}` | Get one truck by id (cross-fleet) | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin, SupplierManager |
| GET | `/trucks` | List trucks across fleets, filterable by fleet | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin, SupplierManager |
| GET | `/cases/{caseId}` | Get one case by id | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin, SupplierManager |
| GET | `/cases` | List cases across fleets and trucks | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin, SupplierManager |
| GET | `/work-orders/{workOrderId}` | Get one work order by id | FleetManager, UptimeCoordinator, DealerAdvisor, WarrantyAdmin |
| GET | `/work-orders` | List work orders across cases | FleetManager, UptimeCoordinator, DealerAdvisor, WarrantyAdmin |
| GET | `/part-orders/{partOrderId}` | Get one part order by id | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin |
| GET | `/part-orders` | List part orders across cases | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager, WarrantyAdmin |
| GET | `/claims/{claimId}` | Get one warranty claim by id | FleetManager, UptimeCoordinator, WarrantyAdmin, SupplierManager |
| GET | `/claims` | List warranty claims across cases | FleetManager, UptimeCoordinator, WarrantyAdmin, SupplierManager |
| GET | `/part-returns/{partReturnId}` | Get one part return by id | DealerAdvisor, WarrantyAdmin, SupplierManager |
| GET | `/part-returns` | List part returns across claims | DealerAdvisor, WarrantyAdmin, SupplierManager |
| GET | `/recoveries/{recoveryId}` | Get one supplier recovery by id | WarrantyAdmin, SupplierManager |
| GET | `/recoveries` | List supplier recoveries across claims | WarrantyAdmin, SupplierManager |
| GET | `/coverage-contracts/{contractId}` | Get one coverage contract by id | FleetManager, UptimeCoordinator, WarrantyAdmin |
| GET | `/coverage-contracts` | List coverage contracts across trucks | FleetManager, UptimeCoordinator, WarrantyAdmin |
| GET | `/fault-events/{faultEventId}` | Get one fault event by id | FleetManager, UptimeCoordinator, DealerAdvisor, WarrantyAdmin |
| GET | `/fault-events` | List fault events across trucks | FleetManager, UptimeCoordinator, DealerAdvisor, WarrantyAdmin |
| GET | `/campaign-completions/{completionId}` | Get one campaign completion row by id | FleetManager, UptimeCoordinator, WarrantyAdmin |
| GET | `/campaign-completions` | List campaign completion rows across campaigns | FleetManager, UptimeCoordinator, WarrantyAdmin |
| GET | `/bays/{bayId}` | Get one service bay by id | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager |
| GET | `/bays` | List service bays across dealers | FleetManager, UptimeCoordinator, DealerAdvisor, PartsManager |
| GET | `/reliability-reports/{reportId}` | Get one reliability report by id | FleetManager, UptimeCoordinator, WarrantyAdmin |
| GET | `/reliability-reports` | List reliability snapshots across fleets | FleetManager, UptimeCoordinator, WarrantyAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_ACTOR_NOT_FOUND` | 404 Not Found |
| `ERR_FLEET_NOT_FOUND` | 404 Not Found |
| `ERR_TRUCK_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_DEALER_NOT_FOUND` | 404 Not Found |
| `ERR_BAY_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PART_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PART_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_RECOVERY_NOT_FOUND` | 404 Not Found |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 Not Found |
| `ERR_FAULT_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_COVERAGE_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_CAMPAIGN_COMPLETION_NOT_FOUND` | 404 Not Found |
| `ERR_FLEET_NOT_ACTIVE` | 409 Conflict |
| `ERR_TRUCK_DECOMMISSIONED` | 409 Conflict |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_CASE_HAS_OPEN_CLAIM` | 409 Conflict |
| `ERR_BAY_TIME_CONFLICT` | 409 Conflict |
| `ERR_DEALER_NOT_AVAILABLE` | 409 Conflict |
| `ERR_CRITICAL_FAULT_WINDOW_LAPSED` | 422 Unprocessable Entity |
| `ERR_RETURN_WINDOW_LAPSED` | 422 Unprocessable Entity |
| `ERR_INVALID_COVERAGE_WINDOW` | 422 Unprocessable Entity |
| `ERR_LABOR_MINUTES_EXCEED_STANDARD` | 422 Unprocessable Entity |
| `ERR_RECOVERY_CLAIM_EXCEEDS_ALLOWANCE` | 422 Unprocessable Entity |
| `ERR_RECOVERY_OVERPAID` | 422 Unprocessable Entity |
| `ERR_INVALID_WORK_ORDER_WINDOW` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_IDENTIFIER` | 409 Conflict |
| `ERR_ODOMETER_REGRESSION` | 422 Unprocessable Entity |
| `ERR_INVALID_CAMPAIGN_WINDOW` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CAMPAIGN_NOT_CLOSABLE` | 409 Conflict |
| `ERR_CASE_NOT_AWAITING_PART` | 409 Conflict |
| `ERR_CAMPAIGN_COMPLETION_MISMATCH` | 409 Conflict |
