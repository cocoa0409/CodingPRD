# Patty Commissary API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Patty Commissary API, the operational backbone of a vertically integrated burger chain that owns its entire supply chain — from dedicated beef suppliers through company-operated commissaries to a bounded network of stores. The business refuses franchising and refuses freezers: every patty is ground, formed, and delivered fresh from a commissary that may only serve stores inside a hard delivery radius, and every store receives refrigerated deliveries on a daily or near-daily cadence because it has no freezer capacity to buffer against missed trucks.

The API governs the full operating loop. A beef supplier must pass recurring quality audits to remain shippable; a failed audit suspends the supplier and cascades through in-flight deliveries and any commissary that depends on it. A commissary's activation is what opens regional entry — no store site may even be proposed against a commissary whose region is not open — and site approval is gated by a strict great-circle radius check and a forward-looking delivery-frequency projection. Stores run a fixed, limited menu whose unlisted variations are handled entirely through register modifiers, and new-store openings trigger a temporary demand-surge mode with its own queue-pacing rules and access to reserve trucks. People operations are equally constrained: wages follow a fixed rung ladder, promotion to manager happens only through an internal posting process with segregation-of-duties controls, and a store's derived staffing posture gates whether new shifts may be scheduled at all.

Because the entire system is driven by a controllable logical clock rather than wall-clock time, all temporal rules — audit staleness, surge windows, shift overlap, delivery gaps — are evaluated against that clock. The sections below define the global contracts first, then the business workflows, then the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the user's operational capacity. The system recognizes exactly seven roles, spelled as follows: `SupplyChainDirector`, `CommissaryPlanner`, `QualityAuditor`, `RealEstatePlanner`, `StoreManager`, `Associate`, and `HRDirector`. A request whose `X-User-Role` header is missing or names anything outside this declared set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `StoreManager`, `X-User-ID` is the `id` of the acting `Associate` — specifically the associate who manages the store in question; ownership checks on store-scoped manager operations compare the store's manager reference to `X-User-ID`. When `X-User-Role` is `Associate`, `X-User-ID` is likewise the `id` of the acting `Associate`; ownership checks compare resource fields that reference an associate — such as the associate taking an order or the candidate on an application — against `X-User-ID`. When `X-User-Role` is `SupplyChainDirector`, `CommissaryPlanner`, `QualityAuditor`, `RealEstatePlanner`, or `HRDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `recorded_by_id` on an `Audit` or `posted_by_id` on a `ManagerPosting`, where the workflow writes it) but does not compare it to any entity's `id`. Where an endpoint requires the entity-backed identity to match a resource's ownership field — an associate serving an order at their own store, a store manager acting on their own store, a candidate withdrawing their own application — a mismatch is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that increments by exactly one on every mutation of the resource. Cascades that touch a resource count as mutations of that resource and increment its `version` accordingly.

All temporal reasoning in the system — audit staleness, surge day indices, shift overlap, delivery gaps, tenure — runs against a **logical clock**, never wall-clock time. Before any operator sets it, the logical clock reads exactly `2026-09-01T00:00:00Z` as a fixed startup default. A `SupplyChainDirector` may advance the clock through an admin-only test-driving capability that accepts a `current_utc` instant and returns the accepted `current_utc`. Advancing the clock does not eagerly rewrite derived state: the store `surge_day_index` and the supplier `days_since_last_passed_audit` are recomputed lazily the next time they are read or consulted by an eligibility check.

### 2.5. Request Evaluation Order

When several validation rules could reject the same request, the server evaluates them in a fixed priority order, and the rejection surfaced to the caller is the first one that fires:

1. **Authentication** — the `X-User-Role` header is present and names a declared role, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is permitted for the endpoint, else `ERR_UNAUTHORIZED`.
3. **Identity and ownership** — entity-backed identity checks (right store, right candidate), else `ERR_FORBIDDEN_ROLE`.
4. **Path existence** — every identifier in the URL path exists, validated left to right, else `ERR_NOT_FOUND`.
5. **Body reference existence** — every foreign-key identifier in the request body (such as `commissary_id`, `supplier_id`, `store_id`, `menu_item_id`, `truck_id`, `production_run_id`, `route_id`, and candidate identifiers) references an existing entity, else `ERR_NOT_FOUND`.
6. **Request shape** — required fields present, types valid, enum values within their declared domains, modifier codes within the unlisted variation set, arrays well-formed, else `ERR_INVALID_REQUEST`.
7. **Optimistic concurrency** — where an endpoint requires an expected parent version, it must match, else `ERR_STALE_VERSION`.
8. **State preconditions** — the target entity is in a state that permits the transition; the per-entity state errors (`ERR_COMMISSARY_INVALID_STATE`, `ERR_STORE_INVALID_STATE`, `ERR_SURGE_ALREADY_ACTIVE`, `ERR_SURGE_NOT_ACTIVE`, `ERR_SUPPLIER_INVALID_STATE`, `ERR_AUDIT_ALREADY_RECORDED`, `ERR_ROUTE_INVALID_STATE`, `ERR_BATCH_INVALID_STATE`, `ERR_DELIVERY_INVALID_STATE`, `ERR_RUN_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`, `ERR_POSTING_INVALID_STATE`, `ERR_APPLICATION_INVALID_STATE`, `ERR_SHIFT_INVALID_STATE`, and the generic `ERR_INVALID_STATE`) live at this tier.
9. **Business safety, then referential, then temporal, then fiscal rules, then remaining business constraints** — cold-chain and audit-freshness checks (`ERR_COLD_CHAIN_VIOLATION`, `ERR_SUPPLIER_AUDIT_STALE`) precede supplier-approval and cross-entity linkage checks (`ERR_SUPPLIER_NOT_APPROVED`, linkage failures as `ERR_INVALID_REQUEST`), which precede radius, delivery-frequency, shift-overlap, and route-window checks (`ERR_RADIUS_LIMIT_EXCEEDED`, `ERR_DELIVERY_FREQUENCY_VIOLATION`, `ERR_SHIFT_OVERLAP`, `ERR_ROUTE_WINDOW_CONFLICT`), which precede capacity, cooler, and inventory checks (`ERR_CAPACITY_EXCEEDED`, `ERR_COOLER_CAPACITY_EXCEEDED`, `ERR_INSUFFICIENT_INVENTORY`), which precede the promotion, segregation-of-duties, staffing-posture, and truck-dispatchability constraints (`ERR_PROMOTION_INELIGIBLE`, `ERR_SOD_VIOLATION`, `ERR_POSTURE_BLOCKS`, `ERR_TRUCK_INACTIVE`).

This ordering matters operationally: a caller whose request fails both a shape check and a state check always sees the shape error first, and a stale-version rejection is surfaced before any state-machine or business-rule rejection.

### 2.6. Nested Resource Retrieval

For any endpoint whose path contains multiple resource identifiers, existence is validated in strict left-to-right order, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the *first* identifier that does not correspond to an existing resource. A request addressing an audit under a non-existent supplier therefore fails on the supplier before the audit is ever consulted.

### 2.7. Optimistic Concurrency Control

Two creation endpoints participate in optimistic concurrency control, and for both the expected-version field is a non-optional input:

- Creating a store requires the request to carry `expected_commissary_version`, the `version` of the target commissary as the client last observed it. If the commissary's current `version` no longer matches — because any prior store creation, truck mutation, beef receipt, production plan, or lifecycle transition has advanced it — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot act on an outdated view of the commissary's capacity and radius posture.
- Planning a delivery batch requires `expected_store_version`, matching the target store's current `version`. Surge toggles, status changes, and prior batch planning all advance the store's version; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) because the client's frequency and mode assumptions are outdated.

Endpoints not listed here do not take a version field at all.

### 2.8. Geographic Discipline: Radius, Distance, and Precision of Measurement

Store siting is governed by great-circle distance. The distance between a store and its assigned commissary is computed with the haversine formula over an Earth radius of 6371.0 kilometres: convert both latitudes to radians, take the differences of latitude and longitude in radians, form the square of the half-chord length from the half-angle sines of the latitude difference and the cosine-weighted half-angle sines of the longitude difference, and recover the central angle as twice the arctangent of the square root of that value over the square root of its complement; the raw distance is the Earth radius multiplied by that angle. The value persisted on the store as `distance_km` is this raw distance rounded half-up to three decimal places — but the radius gate itself always compares the **raw, unrounded** value, and the comparison is strict: the raw distance must be strictly less than the commissary's `radius_limit_km`, or the request is rejected with `ERR_RADIUS_LIMIT_EXCEEDED` (HTTP 422). A site whose raw distance equals the limit exactly is rejected.

### 2.9. Freshness Cadence and Precision Conventions

Because stores have no freezers, delivery cadence is a first-class constraint. A commissary declares which weekdays it runs refrigerated routes through `delivery_days_mask`, an array of seven booleans indexed by weekday with index 0 meaning Monday and index 6 meaning Sunday. Two gap limits recur throughout the system: the normal ceiling of **48 hours** between deliveries, and the tightened ceiling of **24 hours** that applies to high-demand stores and to the first three days of an opening surge. Gap boundaries are always inclusive — a gap of exactly 48.0 hours passes the normal check.

Rounding conventions are pinned per domain. Distances are rounded half-up to three decimal places for storage only. All monetary amounts are integer cents. Modifier charges are rounded half-up **per order line** and then summed; summing raw amounts and rounding once at the end is forbidden. Delivery gaps are expressed in hours to two decimal places. Cooler-case requirements and raw-beef requirements are whole units produced by rounding each component up before summing. The staffing coverage ratio is compared raw, with no rounding.

## 3. Business Logic & Workflows

### 3.1. Beef Sourcing: Suppliers, Audits, and the Suspension Cascade

A `SupplyChainDirector` registers a beef supplier by providing a `supplier_code` (unique across all suppliers, for example `RANCH-01`), a quality `spec_profile`, and an `audit_frequency_days` interval declaring the maximum number of days allowed to elapse between passed audits. The `spec_profile` must contain the numeric keys `lean_point_pct`, `max_fat_pct`, and `max_bacterial_count_cfu_g`, plus the boolean `chilled_never_frozen`. A new supplier starts in `PROBATION` status with `days_since_last_passed_audit` initialized to 0. Supplier `status` cycles through `PROBATION`, `APPROVED`, and `SUSPENDED`, and ends at `RETIRED`.

Quality oversight belongs to the `QualityAuditor`, who schedules an audit for a supplier by providing a `scheduled_date`; the audit begins in `SCHEDULED` status with `completed_at` and `result` both null and `findings` defaulting to an empty string. An audit may be cancelled while `SCHEDULED`, moving it to `CANCELLED`; either action attempted on an audit that is no longer `SCHEDULED` is rejected with `ERR_AUDIT_ALREADY_RECORDED`. Recording a result requires the target audit to be `SCHEDULED` and carries the `result` (`PASS` or `FAIL`) plus optional `findings`; the server stamps `completed_at` from the logical clock and writes the caller's `X-User-ID` into `recorded_by_id` for segregation-of-duties traceability. Recording transitions the audit to `RECORDED` and fires the corresponding supplier transition:

- A recorded `PASS` on a `PROBATION` supplier moves it to `APPROVED`. A recorded `PASS` on an `APPROVED` supplier leaves it `APPROVED` as a renewal. A recorded `PASS` on a `SUSPENDED` supplier lifts it back to `APPROVED`. In every passing case the supplier's `days_since_last_passed_audit` is reset to 0, restarting the stale-audit clock, and both the supplier's and the audit's `version` increment.
- A recorded `FAIL` on a `PROBATION` or `APPROVED` supplier moves it to `SUSPENDED` and fires the **suspension cascade**, whose propagation order is pinned as a single pass, deliveries first, then commissaries: every `BeefDelivery` of that supplier in `SCHEDULED` or `IN_TRANSIT` status moves to `REJECTED`, processed in ascending `created_at` order; then every `Commissary` whose `supplier_id` is that supplier and whose status is `OPERATIONAL` is demoted to `BUILDING` with `regional_entry_open` recomputed to false, each demoted commissary's `version` incrementing alongside the supplier's and the audit's. Recording an audit against a supplier in any other status is rejected with `ERR_SUPPLIER_INVALID_STATE`.

A supplier may only be retired from `APPROVED`; retirement by a `SupplyChainDirector` moves it to `RETIRED` and cancels every `SCHEDULED` delivery of that supplier, while deliveries already `IN_TRANSIT` are left for the receiving decision. Retirement from any other status is rejected with `ERR_SUPPLIER_INVALID_STATE`.

Freshness is enforced independently of status. Whenever a beef shipment is dispatched or its receipt confirmed, the system counts the whole calendar days between the most recent `PASS` audit's `completed_at` (considering `RECORDED` audits only) and the logical clock; a supplier is eligible only while it is `APPROVED` **and** that day count is less than or equal to its `audit_frequency_days`. The boundary is inclusive: a count exactly equal to `audit_frequency_days` is eligible, and one day beyond it is not, surfacing `ERR_SUPPLIER_AUDIT_STALE` (HTTP 422). Separately, any operation that requires an approved supplier — beginning a commissary build, shipping beef, or confirming receipt — is rejected with `ERR_SUPPLIER_NOT_APPROVED` (HTTP 422) when the referenced supplier holds any other status.

### 3.2. Commissary Lifecycle and Regional Entry

A `SupplyChainDirector` registers a commissary with a `name`, geographic `lat` and `lng` in decimal degrees, a hard `radius_limit_km`, three daily production ceilings — `daily_patty_capacity`, `daily_bun_capacity`, and `daily_produce_capacity` (produce measured in lettuce/tomato/onion prep units) — the `delivery_days_mask` route calendar, and the `supplier_id` of its dedicated beef supplier. A new commissary starts in `PLANNING` with `raw_beef_lbs_on_hand` at 0 and `regional_entry_open` false. While the commissary is `PLANNING` or `BUILDING`, the director may still revise its configuration — the radius limit, the three daily capacities, or the delivery-days mask — each such update incrementing the commissary's `version`.

The lifecycle is cyclic. Beginning the build moves `PLANNING` to `BUILDING` and requires the dedicated supplier to be `APPROVED` at that moment (`ERR_SUPPLIER_NOT_APPROVED` otherwise). Activation moves `BUILDING` to `OPERATIONAL` and flips `regional_entry_open` to true — this is the exact moment regional entry opens and store-site creation against this commissary becomes legal. Recertification moves `OPERATIONAL` back to `BUILDING`, closing regional entry again by recomputing `regional_entry_open` to false, and is permitted only while no delivery batch of this commissary sits in `PLANNED` or `LOADED` status; open batches block it with `ERR_OPEN_BATCHES_EXIST` (HTTP 409). Decommissioning moves `OPERATIONAL` to the terminal `DECOMMISSIONED` state and is permitted only when every store supplied by the commissary is already `CLOSED` (`ERR_STORES_STILL_OPEN` otherwise); it cascades by retiring every `ACTIVE` truck of the commissary to `INACTIVE` and cancelling every `DRAFT` route of the commissary (routes already `FINALIZED` or `COMPLETED` are untouched), and it too recomputes `regional_entry_open` to false. Any lifecycle action attempted from the wrong status is rejected with `ERR_COMMISSARY_INVALID_STATE` (HTTP 409), and each successful transition increments the commissary's `version`.

The raw-beef ledger on the commissary is conserved: `raw_beef_lbs_on_hand` is credited when a beef delivery's receipt is confirmed and debited when a production run is planned, and a cancelled production run restores its debit exactly. Nothing else may move this balance.

### 3.3. Receiving Beef and Planning Production

Beef arrives through deliveries scheduled by a `CommissaryPlanner` with a `commissary_id`, a `supplier_id`, a `shipped_at` timestamp, the `raw_beef_lbs` shipped, and the recorded `transit_temp_celsius`. Dedicated processing is enforced structurally: the delivery's `supplier_id` must equal the receiving commissary's own `supplier_id`, or the request fails the cross-entity linkage check with `ERR_INVALID_REQUEST`. A scheduled delivery moves from `SCHEDULED` to `IN_TRANSIT` when shipped — allowed only while the supplier is `APPROVED` and audit-fresh — and from `IN_TRANSIT` it either is received or is rejected. Confirming receipt enforces the cold chain: `transit_temp_celsius` must be less than or equal to 4.0 degrees; any strictly greater reading is rejected with `ERR_COLD_CHAIN_VIOLATION` (HTTP 422) and the shipment cannot be received. A successful confirmation moves the delivery to `RECEIVED` and credits the commissary's `raw_beef_lbs_on_hand` by the delivery's `raw_beef_lbs`, incrementing both the delivery's and the commissary's `version`. Rejecting a delivery — whether from `SCHEDULED` or `IN_TRANSIT`, by explicit operator action or by the supplier-suspension cascade — moves it to `REJECTED` with no inventory credit. Wrong-state delivery actions are rejected with `ERR_DELIVERY_INVALID_STATE`.

Production is planned per commissary per day. Planning a run takes a `run_date` plus `patties_planned`, `buns_planned`, and `produce_units_planned`. Four capacity gates guard planning, all surfacing `ERR_CAPACITY_EXCEEDED` (HTTP 422): planned patties may not exceed `daily_patty_capacity`, planned buns may not exceed `daily_bun_capacity`, planned produce may not exceed `daily_produce_capacity`, and the run's raw-beef requirement may not exceed the commissary's `raw_beef_lbs_on_hand`. That requirement is recorded on the run as `beef_lbs_required`: the planned patties divided by the standard patties-per-pound yield, rounded up to a whole pound. Planning a run immediately debits `beef_lbs_required` from the commissary's raw-beef ledger and increments the commissary's `version`.

A run begins `PLANNED`. Completing it moves it to `COMPLETED`, making its finished goods available for batch loading. Cancelling is only possible while `PLANNED` and only while no batch referencing the run is in `LOADED` status — a loaded batch blocks cancellation with `ERR_BATCHES_NOT_DELIVERED` (HTTP 409). Cancellation reverses the beef debit as a compensating action, adding `beef_lbs_required` back to `raw_beef_lbs_on_hand` and incrementing both the run's and the commissary's `version`. Wrong-state run actions are rejected with `ERR_RUN_INVALID_STATE`.

### 3.4. Store Siting, Approval, and the Opening Surge

A `RealEstatePlanner` proposes a store site against a specific commissary, supplying the `commissary_id`, a `name`, the site's `lat` and `lng`, optionally a `manager_associate_id`, and the mandatory `expected_commissary_version` described in §2.7. Two gates run already at creation: the referenced commissary must have `regional_entry_open` true (a linkage failure otherwise), and the raw haversine distance must pass the strict radius check of §2.8 (`ERR_RADIUS_LIMIT_EXCEEDED` otherwise). A created store lands in `SITE_REVIEW` with `opening_mode` `NORMAL`, its `distance_km` display value computed, and its `staffing_posture` derived from the (initially empty) crew; the creation itself mutates the commissary and increments `Commissary.version`.

Approval moves `SITE_REVIEW` to `APPROVED` and re-runs the siting gates plus a staffing prerequisite: the store's `manager_associate_id` must be non-null and must reference an associate whose `current_level` is `MANAGER` (`ERR_INVALID_REQUEST` otherwise — the field may stay null during `SITE_REVIEW` as a bootstrap courtesy, but never past approval). Approval also re-checks the radius and runs the **delivery-day gap projection**: starting from the current logical-clock day, the system scans a fourteen-day horizon and marks each day delivery-capable when the commissary's `delivery_days_mask` allows that weekday — with one surge carve-out, that for a store already `OPEN` and in `OPENING_SURGE`, surge days one through three are not delivery-capable on Sundays (the near-daily weekdays, Monday through Saturday, remain capable). The projection fails unless at least two capable days exist in the window and the worst gap between consecutive capable days, measured in hours, stays within the store's effective maximum gap: 48 hours for a standard store, tightened to 24 hours for a store whose weekly patty demand class exceeds the high-demand threshold. A failed projection is rejected with `ERR_DELIVERY_FREQUENCY_VIOLATION` (HTTP 422). Approval and the subsequent move from `APPROVED` to `OPEN` are both `RealEstatePlanner` actions; wrong-state attempts surface `ERR_STORE_INVALID_STATE`.

An `OPEN` store may enter **opening surge** mode through its own `StoreManager`. Entering surge requires the store to be `OPEN` and currently in `NORMAL` mode (`ERR_SURGE_ALREADY_ACTIVE` otherwise); it leaves `status` untouched but flips `opening_mode` to `OPENING_SURGE`, stamps `surge_start_date` with the current logical-clock day, sets `surge_end_date` to the seventh day of the window — the start day plus six — and sets `surge_day_index` to 1. While surging, `surge_day_index` tracks the one-based calendar-day index into the window: the floor of the whole-day distance from `surge_start_date` to the clock day, plus one. Ending the surge requires `OPENING_SURGE` to be active (`ERR_SURGE_NOT_ACTIVE` otherwise) and clears `surge_day_index`, `surge_start_date`, and `surge_end_date` back to null while restoring `opening_mode` to `NORMAL`. Both toggles increment the store's `version`. Surge also governs the fleet: while at least one store of a commissary is in `OPENING_SURGE`, that commissary's `ACTIVE` reserve trucks become dispatch-eligible, and when the surge ends they become ineligible again — this eligibility is evaluated live from truck status, route type, and the presence of a surging store, and neither toggle mutates any truck row or the commissary.

Closing a store — a `RealEstatePlanner` action from `OPEN` to the terminal `CLOSED` — is blocked while any shift of the store remains `SCHEDULED` with a `shift_end` later than the logical clock (`ERR_OPEN_SHIFTS_EXIST`, HTTP 409). A successful close cascades: every `PLANNED` delivery batch of the store moves to `CANCELLED` (loaded or delivered batches are untouched); every delivery route listing the store in its `store_ids` that is `DRAFT` or `FINALIZED` moves to `CANCELLED`, each cancelled route's `version` incrementing; and every `SCHEDULED` shift assignment of the store moves to `CANCELLED`.

### 3.5. Fleet, Routes, and Batch Delivery

A `CommissaryPlanner` registers trucks at a commissary with a `plate`, a `route_type` of `PRIMARY` or `RESERVE`, and a `cooler_capacity_cases`; the plate must be unique among trucks whose status is `ACTIVE`, and a new truck starts `ACTIVE`. Retiring a truck moves it to `INACTIVE` (attempted on an already-inactive truck, `ERR_TRUCK_INACTIVE`) and increments both the truck's and its commissary's `version`.

A delivery route is drafted for a commissary with a `truck_id`, a `service_date` (the calendar day served, at 00:00:00Z), and an ordered `store_ids` stop sequence; it starts `DRAFT`. Finalizing a route is where the fleet rules bite, in this order of concerns: the route must still be `DRAFT` (`ERR_ROUTE_INVALID_STATE` otherwise); the assigned truck must be `ACTIVE`, and if it is a `RESERVE` truck then at least one store on the stop list must currently be in `OPENING_SURGE` — both failures surface `ERR_TRUCK_INACTIVE` (HTTP 422); the aggregate cooler check must pass, meaning the sum of `cooler_cases_required` over every batch already `LOADED` on the route plus every candidate case increment must not exceed the truck's `cooler_capacity_cases` (`ERR_COOLER_CAPACITY_EXCEEDED`); every store on the route must have the service date inside its delivery-day window — the weekday permitted by the commissary's mask and the gap versus the store's previous delivered batch within the store's effective maximum — with window failures surfacing as `ERR_DELIVERY_WINDOW_CONFLICT`; and temporal exclusivity must hold, so the truck may not already be committed to another `FINALIZED` route on the same `service_date`, nor may any store on the stop list already be visited by another `FINALIZED` route that day — routes on adjacent days never conflict — with violations rejected as `ERR_ROUTE_WINDOW_CONFLICT` (HTTP 422). Completing a route requires it to be `FINALIZED` and every batch riding it to be `DELIVERED` (`ERR_BATCHES_NOT_DELIVERED` otherwise), moving it to `COMPLETED`. Cancelling is permitted from `DRAFT` or `FINALIZED`, by explicit planner action or by the store-close and commissary-decommission cascades, and moves the route to `CANCELLED`.

Delivery batches are the unit of goods movement. Planning a batch against a store takes the `store_id`, a `delivery_date` at 00:00:00Z, and the commodity quantities `patty_count`, `bun_count`, and `produce_units`, plus the mandatory `expected_store_version` of §2.7. At planning time the system copies the store's `commissary_id` onto the batch, computes `cooler_cases_required`, leaves `production_run_id` and `route_id` null, and increments the store's `version`; the batch starts `PLANNED`. The cooler computation rounds each commodity up separately — patties in cases of 40, buns in cases of 48, produce in cases of 12 — and sums the three whole-case counts.

Loading a batch binds it to a production run and a route. The run must be `COMPLETED` and belong to the batch's commissary (`ERR_RUN_NOT_COMPLETED`, HTTP 422, otherwise). The route must be `DRAFT` or `FINALIZED`, belong to the batch's commissary, serve exactly the batch's `delivery_date`, and list the batch's store in its `store_ids` (`ERR_ROUTE_INVALID_STATE` otherwise). Loading computes `gap_hours_at_load`: the system finds the store's most recent `DELIVERED` batch whose `delivered_at` precedes this batch's `delivery_date` — ties on equal `delivered_at` are broken toward the later `created_at`, never by identifier — and measures the hours between that `delivered_at` and this batch's `delivery_date` at 00:00Z, expressed to two decimal places. For the store's first loaded batch the gap is null and the store is exempt from the gap check; otherwise the gap must be less than or equal to the store's effective maximum — 24 hours during surge days one through three and for high-demand stores, 48 hours otherwise, with exactly 48.0 hours passing — failing with `ERR_DELIVERY_FREQUENCY_VIOLATION`. The aggregate truck cooler check of loaded-plus-candidate cases against `cooler_capacity_cases` runs again at load time (`ERR_COOLER_CAPACITY_EXCEEDED`). A successful load stamps `production_run_id`, `route_id`, `cooler_cases_required`, and `gap_hours_at_load` and moves the batch to `LOADED`.

Delivery requires the batch to be `LOADED` and its route to be `FINALIZED` (`ERR_ROUTE_INVALID_STATE` otherwise). Delivering stamps `delivered_at` from the logical clock, moves the batch to `DELIVERED`, and credits the store's on-hand inventory ledger with the batch's `patty_count`, `bun_count`, and `produce_units`. Cancelling a batch is possible only from `PLANNED` (`ERR_BATCH_INVALID_STATE` on any other state) and moves it to `CANCELLED`.

### 3.6. Register Operations: Menu, Modifiers, Orders, and Store Inventory

The menu is fixed and limited. A `SupplyChainDirector` creates menu items with a unique `sku`, a `name`, a listed `base_price_cents`, the base `patty_count` and base `produce_units` per unit before modifiers, and an `active` flag that defaults to true. Unlisted variations are handled entirely through register modifiers drawn from a fixed set of four codes — `EXTRA_PATTY`, `ANIMAL_STYLE`, `PROTEIN_STYLE`, and `WELL_DONE`; any other code in an order line is a shape error.

An `Associate` places an order at their own store by submitting `placed_by_associate_id` and the `lines` array, each line carrying a `menu_item_id`, a `qty`, and a `modifier_codes` list. Pricing follows a pinned order. The base total, `base_total_cents`, is the sum over lines of the item's `base_price_cents` multiplied by the line's `qty`. The modifier charge is computed per line first: the line's modifier unit count is its `qty` multiplied by one plus the number of `EXTRA_PATTY` codes on the line; the line's pre-discount modifier amount is that unit count multiplied by each modifier code's unit price — 150 cents for `EXTRA_PATTY`, 65 cents for `ANIMAL_STYLE`, and 0 cents for both `PROTEIN_STYLE` and `WELL_DONE` — summed across the line's modifier codes; and when `WELL_DONE` appears on the line, the pre-discount amount is reduced by ten percent. Each line's modifier amount is rounded half-up to whole cents individually, and `modifier_charge_cents` is the sum of those rounded line amounts — rounding only once at the end is forbidden. The order's `total_price_cents` is `base_total_cents` plus `modifier_charge_cents`. The response quote computed before placement commits and the value persisted on the order use identical arithmetic and must always be equal for the same payload.

Placement also reserves inventory from the store's on-hand ledger — the ledger credited by batch delivery, debited by order placement, and re-credited by order cancellation. The reservation footprint is computed per line and summed: patties as `qty` times the item's `patty_count` plus the count of `EXTRA_PATTY` codes on the line; buns as exactly one per unit sold, so `qty` per line regardless of modifiers; produce as `qty` times the item's `produce_units`. The total patties are recorded as `patties_reserved`. The check is an all-or-nothing waterfall: all three commodities must be satisfiable, and if any one is short, nothing is debited and the order is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 422) — there are no partial fills. Note the zero-quantity edge: an order whose lines total zero patties — grilled-cheese-style units with `patty_count` 0 — still reserves buns and produce, and a store holding zero buns rejects it.

Queue mechanics depend on the store's mode. On every placement the order's `queue_position` is the count of that store's orders currently in `PLACED` status plus one. When the store is in `OPENING_SURGE`, a pacing delay is also computed and stored as `surge_pacing_minutes`: first the surge day index is recomputed from the clock, and if it has moved beyond the seven-day window the store's `opening_mode` auto-reverts to `NORMAL` and no pacing applies; otherwise the number of currently `PLACED` orders is divided by ten and floored to an intensity, the raw pacing is the intensity times five minutes, and the effective pacing is the raw value clamped from below at a five-minute floor and from above at a per-day cap — 45 minutes on surge days one through three, 30 minutes on days four and five, and 20 minutes on days six and seven.

An order begins `PLACED` and ends `SERVED` or `CANCELLED`; actions on an order no longer `PLACED` are rejected with `ERR_ORDER_INVALID_STATE`. Serving is performed by an `Associate` whose `home_store_id` matches the order's store and whose `active` flag is true — anyone else is rejected with `ERR_FORBIDDEN_ROLE` — and clears `queue_position` to null. Cancelling, likewise restricted to an associate of the order's store, performs the compensating action: the store's on-hand inventory is credited back by the reserved patties and the corresponding bun and produce quantities computed from the lines, returning the ledger to its pre-placement value, and `queue_position` is cleared.

### 3.7. People Operations: Hiring, the Wage Ladder, Staffing Posture, and Internal Management Sourcing

An `HRDirector` hires an associate with a `full_name`, a `hired_date`, a `home_store_id`, and an optional `active` flag defaulting to true. Every hire starts at `current_level` `LEVEL_1` with an `hourly_wage_cents` of 1750 and a `promotion_count` of 0, and hiring recomputes the home store's staffing posture. The director may also update an associate's `active` flag or `home_store_id`, which recomputes the posture of every affected store.

Compensation follows a fixed seven-rung ladder, and each rung maps to exactly one wage in cents: `LEVEL_1` at 1750, `LEVEL_2` at 1850, `LEVEL_3` at 1975, `LEVEL_4` at 2100, `LEVEL_5` at 2250, `SHIFT_LEAD` at 2500, and `MANAGER` at 3200. Promotion by an `HRDirector` advances exactly one rung along this order and is gated by four conditions, all enforced with the boundary inclusivity stated: the associate's tenure — whole calendar days from `hired_date` to the clock date — must be at least 180 days; the associate must hold at least 2 `SCHEDULED` shifts whose `shift_start` is at or after the current clock time; their `promotion_count` must be below 6; and their `current_level` must not already be `MANAGER`. Any failure is rejected with `ERR_PROMOTION_INELIGIBLE` (HTTP 422). A successful promotion moves the associate to the next rung, recomputes `hourly_wage_cents` from the ladder, increments `promotion_count` by one, increments the associate's `version`, and recomputes the home store's staffing posture. The `MANAGER` rung is never reachable through promotion — it is reachable only through the internal posting process below.

A store's `staffing_posture` is a derived field, not a state-machine state, recomputed after every shift creation, shift cancellation, associate hire, and associate deactivation affecting that store. The evaluation order is pinned, coverage first: let the active crew be the associates whose `home_store_id` is the store and whose `active` flag is true, and let today's scheduled coverage be the store's `SCHEDULED` shifts whose window contains the current clock time (`shift_start` at or before the clock and `shift_end` after it). The coverage ratio is today's scheduled count divided by the active crew size, with a crew of zero treated as one to avoid division by zero. If the coverage ratio is below 0.60, the posture is `CRITICAL` — this check runs first. Otherwise, if the active crew contains no associate at `MANAGER` level, the posture is `CRITICAL`. Otherwise, if the active crew contains fewer than 1 associate at `SHIFT_LEAD` or `MANAGER` level combined, the posture is `STRAINED`. Otherwise the posture is `STEADY`. Posture gates scheduling: creating a shift is blocked with `ERR_POSTURE_BLOCKS` (HTTP 422) whenever the posture is `CRITICAL`, and during `OPENING_SURGE` a `STRAINED` posture is treated as `CRITICAL` for this gate.

Shift scheduling itself belongs to the `StoreManager` of the store in question or to an `HRDirector` acting anywhere. Creating a shift takes an `associate_id`, a `shift_start`, and a `shift_end`; the end must be after the start, and the same associate may not hold two `SCHEDULED` shifts whose half-open intervals — start inclusive, end exclusive — overlap, a violation rejected with `ERR_SHIFT_OVERLAP` (HTTP 422). A new shift starts `SCHEDULED`, and its creation recomputes the store's posture. Cancelling a shift requires it to be `SCHEDULED` (`ERR_SHIFT_INVALID_STATE` otherwise), moves it to `CANCELLED`, and recomputes posture again on removal.

Store management is sourced internally only. An `HRDirector` posts a manager opening for a store, supplying the `store_id`; the posting starts `OPEN`, the server records the caller's `X-User-ID` as `posted_by_id`, and `filled_by_associate_id` stays null until the posting closes. An `Associate` applies to a posting by submitting a `candidate_associate_id`; the application records which posting it targets through its `posting_id`. The candidate must be an active associate currently at `SHIFT_LEAD`, must not be the posting store's current manager as recorded in the store's `manager_associate_id`, and the posting must be `OPEN` — breaches of this internal-sourcing rule surface `ERR_SOD_VIOLATION` (HTTP 422), and a posting that is not `OPEN` surfaces `ERR_POSTING_INVALID_STATE`. Applications start `PENDING`, and the candidate may withdraw their own application while it is `PENDING` — anyone else attempting the withdrawal is rejected with `ERR_FORBIDDEN_ROLE`, and a non-`PENDING` application with `ERR_APPLICATION_INVALID_STATE` — moving it to `WITHDRAWN`.

Closing a posting is where segregation of duties bites: the `HRDirector` who closes must not be the one whose `X-User-ID` was recorded as `posted_by_id` (`ERR_SOD_VIOLATION` otherwise). The close request names a `candidate_application_id`, which must reference a `PENDING` application on this posting (`ERR_APPLICATION_INVALID_STATE` otherwise). A successful close writes the application's `candidate_associate_id` into `filled_by_associate_id`, moves the selected application to `ACCEPTED`, cascades every other `PENDING` application on the posting to `REJECTED`, and promotes the candidate: `current_level` moves from `SHIFT_LEAD` to `MANAGER`, `hourly_wage_cents` is recomputed from the ladder to the manager wage, `promotion_count` increments by one as a compounding internal promotion, the candidate's `home_store_id` moves to the posting's store, and that store's `manager_associate_id` is updated to the candidate. The posting's and the candidate associate's `version` both increment. Cancelling an `OPEN` posting instead moves it to `CANCELLED` and cascades every `PENDING` application to `REJECTED`. Both `ACCEPTED` and `REJECTED` outcomes for applications arise only from these system cascades — no operator endpoint sets them directly.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Successful responses return the created or updated resource in the envelope's `data` field per §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-09-01T00:00:00Z) | SupplyChainDirector |
| POST | `/v1/suppliers` | Register a beef supplier (starts PROBATION) | SupplyChainDirector |
| GET | `/v1/suppliers` | List suppliers | SupplyChainDirector, QualityAuditor, CommissaryPlanner |
| GET | `/v1/suppliers/{id}` | Get a supplier | SupplyChainDirector, QualityAuditor, CommissaryPlanner |
| POST | `/v1/suppliers/{id}/retire` | Retire an APPROVED supplier | SupplyChainDirector |
| POST | `/v1/suppliers/{id}/audits` | Schedule an audit for a supplier | QualityAuditor |
| GET | `/v1/suppliers/{id}/audits` | List audits of a supplier | QualityAuditor, SupplyChainDirector |
| GET | `/v1/audits/{id}` | Get an audit | QualityAuditor, SupplyChainDirector |
| POST | `/v1/suppliers/{id}/audits/{auditId}/record-audit` | Record a scheduled audit's result (PASS or FAIL); fires supplier transitions and cascades | QualityAuditor |
| POST | `/v1/suppliers/{id}/audits/{auditId}/cancel` | Cancel a scheduled audit | QualityAuditor |
| POST | `/v1/commissaries` | Register a commissary (starts PLANNING) | SupplyChainDirector |
| GET | `/v1/commissaries` | List commissaries (filterable by supplier) | SupplyChainDirector, CommissaryPlanner, RealEstatePlanner |
| GET | `/v1/commissaries/{id}` | Get a commissary | SupplyChainDirector, CommissaryPlanner, RealEstatePlanner |
| PATCH | `/v1/commissaries/{id}` | Update commissary configuration while PLANNING or BUILDING | SupplyChainDirector |
| POST | `/v1/commissaries/{id}/begin-build` | Move a commissary from PLANNING to BUILDING (requires APPROVED supplier) | SupplyChainDirector |
| POST | `/v1/commissaries/{id}/activate` | Move a commissary from BUILDING to OPERATIONAL; opens regional entry | SupplyChainDirector |
| POST | `/v1/commissaries/{id}/recertify` | Move a commissary from OPERATIONAL back to BUILDING (no open batches) | SupplyChainDirector |
| POST | `/v1/commissaries/{id}/decommission` | Move a commissary from OPERATIONAL to DECOMMISSIONED (all stores closed) | SupplyChainDirector |
| POST | `/v1/commissaries/{id}/trucks` | Register a truck at a commissary | CommissaryPlanner |
| GET | `/v1/commissaries/{id}/trucks` | List trucks of a commissary | CommissaryPlanner, SupplyChainDirector |
| GET | `/v1/trucks/{id}` | Get a truck | CommissaryPlanner, SupplyChainDirector |
| POST | `/v1/trucks/{id}/retire` | Retire a truck from ACTIVE to INACTIVE | CommissaryPlanner |
| POST | `/v1/routes` | Create a DRAFT delivery route for a service date with an ordered stop list | CommissaryPlanner |
| GET | `/v1/commissaries/{id}/routes` | List routes of a commissary | CommissaryPlanner, SupplyChainDirector |
| GET | `/v1/routes/{id}` | Get a route | CommissaryPlanner, SupplyChainDirector |
| GET | `/v1/routes` | List routes across commissaries (filterable by truck or commissary) | CommissaryPlanner, SupplyChainDirector |
| POST | `/v1/routes/{id}/finalize` | Finalize a DRAFT route with full window, capacity, and truck checks | CommissaryPlanner |
| POST | `/v1/routes/{id}/complete` | Complete a FINALIZED route once all loaded batches are DELIVERED | CommissaryPlanner |
| POST | `/v1/routes/{id}/cancel` | Cancel a DRAFT or FINALIZED route | CommissaryPlanner |
| POST | `/v1/menu-items` | Create a fixed-menu item | SupplyChainDirector |
| GET | `/v1/menu-items` | List menu items | SupplyChainDirector, CommissaryPlanner, Associate, StoreManager, RealEstatePlanner, HRDirector, QualityAuditor |
| GET | `/v1/menu-items/{id}` | Get a menu item | SupplyChainDirector, CommissaryPlanner, Associate, StoreManager |
| POST | `/v1/stores` | Propose a store site (SITE_REVIEW); radius and regional-entry gates plus commissary OCC run at creation | RealEstatePlanner |
| GET | `/v1/stores` | List stores | RealEstatePlanner, SupplyChainDirector, CommissaryPlanner, HRDirector |
| GET | `/v1/stores/{id}` | Get a store | RealEstatePlanner, SupplyChainDirector, CommissaryPlanner, StoreManager, HRDirector |
| POST | `/v1/stores/{id}/approve` | Approve a site (radius, manager, and delivery-frequency checks) | RealEstatePlanner |
| POST | `/v1/stores/{id}/open` | Open an approved store | RealEstatePlanner |
| POST | `/v1/stores/{id}/close` | Close an open store; cascades to batches, routes, and shifts | RealEstatePlanner |
| POST | `/v1/stores/{id}/begin-opening-surge` | Enter OPENING_SURGE mode (seven-day window); activates reserve trucks | StoreManager |
| POST | `/v1/stores/{id}/end-opening-surge` | Exit OPENING_SURGE mode | StoreManager |
| POST | `/v1/batches` | Plan a delivery batch for a store; OCC on the store's version | CommissaryPlanner |
| GET | `/v1/stores/{id}/batches` | List batches of a store | CommissaryPlanner, StoreManager, SupplyChainDirector |
| GET | `/v1/batches/{id}` | Get a batch | CommissaryPlanner, StoreManager, SupplyChainDirector |
| GET | `/v1/batches` | List batches across stores (filterable by commissary, run, route, status) | CommissaryPlanner, SupplyChainDirector |
| POST | `/v1/batches/{id}/load` | Load a PLANNED batch onto a route from a completed production run; gap and cooler checks | CommissaryPlanner |
| POST | `/v1/batches/{id}/deliver` | Deliver a LOADED batch (route must be FINALIZED); credits store inventory | CommissaryPlanner |
| POST | `/v1/batches/{id}/cancel` | Cancel a PLANNED batch | CommissaryPlanner |
| POST | `/v1/stores/{id}/orders` | Place an order at a store register; modifier pricing, inventory reservation, surge pacing | Associate |
| GET | `/v1/stores/{id}/orders` | List orders of a store | Associate, StoreManager |
| GET | `/v1/orders/{id}` | Get an order | Associate, StoreManager |
| GET | `/v1/orders` | List orders across stores (filterable by associate, store, status) | StoreManager, HRDirector |
| POST | `/v1/orders/{id}/serve` | Serve a PLACED order (associate of the order's store) | Associate |
| POST | `/v1/orders/{id}/cancel` | Cancel a PLACED order; inventory credited back | Associate |
| POST | `/v1/associates` | Hire an associate at LEVEL_1 | HRDirector |
| GET | `/v1/associates` | List associates | HRDirector, StoreManager |
| GET | `/v1/associates/{id}` | Get an associate | HRDirector, StoreManager, Associate |
| GET | `/v1/associates/{id}/manager-postings-filled` | List manager postings filled by this associate | HRDirector |
| PATCH | `/v1/associates/{id}` | Update an associate (active flag, home store) | HRDirector |
| POST | `/v1/associates/{id}/promote` | Promote one rung (never to MANAGER) if tenure, shift, and count gates pass | HRDirector |
| POST | `/v1/manager-postings` | Post an internal manager opening for a store | HRDirector |
| GET | `/v1/stores/{id}/manager-postings` | List postings of a store | HRDirector, StoreManager, Associate |
| GET | `/v1/manager-postings/{id}` | Get a posting | HRDirector, StoreManager, Associate |
| POST | `/v1/manager-postings/{id}/applications` | An internal SHIFT_LEAD applies to a posting | Associate |
| GET | `/v1/manager-postings/{id}/applications` | List applications of a posting | HRDirector, Associate |
| GET | `/v1/manager-applications` | List applications across postings (filterable by candidate, status) | HRDirector |
| GET | `/v1/associates/{id}/manager-applications` | List an associate's own manager applications | HRDirector, Associate |
| POST | `/v1/manager-applications/{id}/withdraw` | Candidate withdraws their own application | Associate |
| POST | `/v1/manager-postings/{id}/close` | Close a posting, promoting the selected SHIFT_LEAD to MANAGER (closer must differ from poster) | HRDirector |
| POST | `/v1/manager-postings/{id}/cancel` | Cancel an open posting; pending applications rejected | HRDirector |
| POST | `/v1/stores/{id}/shifts` | Schedule an associate shift (overlap and posture gates) | StoreManager, HRDirector |
| GET | `/v1/stores/{id}/shifts` | List shifts of a store | StoreManager, HRDirector |
| GET | `/v1/shifts/{id}` | Get a shift | StoreManager, HRDirector |
| GET | `/v1/shifts` | List shifts across stores (filterable by associate, store) | StoreManager, HRDirector |
| POST | `/v1/shifts/{id}/cancel` | Cancel a scheduled shift | StoreManager |
| POST | `/v1/beef-deliveries` | Schedule a beef delivery from the commissary's dedicated supplier | CommissaryPlanner |
| GET | `/v1/commissaries/{id}/beef-deliveries` | List beef deliveries for a commissary | CommissaryPlanner, SupplyChainDirector |
| GET | `/v1/beef-deliveries/{id}` | Get a beef delivery | CommissaryPlanner, SupplyChainDirector |
| GET | `/v1/beef-deliveries` | List beef deliveries across commissaries (filterable by supplier, commissary, status) | CommissaryPlanner, SupplyChainDirector |
| POST | `/v1/beef-deliveries/{id}/ship` | Ship a SCHEDULED delivery (supplier APPROVED and audit-fresh) | CommissaryPlanner |
| POST | `/v1/beef-deliveries/{id}/confirm-receiving` | Confirm receipt of an IN_TRANSIT delivery; cold-chain check; credits commissary raw beef | CommissaryPlanner |
| POST | `/v1/beef-deliveries/{id}/reject-receiving` | Reject a delivery; no inventory credit | CommissaryPlanner |
| POST | `/v1/commissaries/{id}/production-runs` | Plan a production run; capacity and raw-beef debit | CommissaryPlanner |
| GET | `/v1/commissaries/{id}/production-runs` | List production runs of a commissary | CommissaryPlanner, SupplyChainDirector |
| GET | `/v1/production-runs/{id}` | Get a production run | CommissaryPlanner, SupplyChainDirector |
| POST | `/v1/production-runs/{id}/complete` | Complete a PLANNED run; goods become loadable | CommissaryPlanner |
| POST | `/v1/production-runs/{id}/cancel` | Cancel a PLANNED run; raw-beef debit reversed | CommissaryPlanner |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the rules that raise them.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_COMMISSARY_INVALID_STATE` | 409 |
| `ERR_STORE_INVALID_STATE` | 409 |
| `ERR_SURGE_ALREADY_ACTIVE` | 409 |
| `ERR_SURGE_NOT_ACTIVE` | 409 |
| `ERR_SUPPLIER_INVALID_STATE` | 409 |
| `ERR_AUDIT_ALREADY_RECORDED` | 409 |
| `ERR_ROUTE_INVALID_STATE` | 409 |
| `ERR_BATCH_INVALID_STATE` | 409 |
| `ERR_DELIVERY_INVALID_STATE` | 409 |
| `ERR_RUN_INVALID_STATE` | 409 |
| `ERR_ORDER_INVALID_STATE` | 409 |
| `ERR_POSTING_INVALID_STATE` | 409 |
| `ERR_APPLICATION_INVALID_STATE` | 409 |
| `ERR_SHIFT_INVALID_STATE` | 409 |
| `ERR_COLD_CHAIN_VIOLATION` | 422 |
| `ERR_SUPPLIER_AUDIT_STALE` | 422 |
| `ERR_SUPPLIER_NOT_APPROVED` | 422 |
| `ERR_RADIUS_LIMIT_EXCEEDED` | 422 |
| `ERR_DELIVERY_FREQUENCY_VIOLATION` | 422 |
| `ERR_SHIFT_OVERLAP` | 422 |
| `ERR_ROUTE_WINDOW_CONFLICT` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_COOLER_CAPACITY_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_INVENTORY` | 422 |
| `ERR_PROMOTION_INELIGIBLE` | 422 |
| `ERR_SOD_VIOLATION` | 422 |
| `ERR_POSTURE_BLOCKS` | 422 |
| `ERR_TRUCK_INACTIVE` | 422 |
| `ERR_OPEN_BATCHES_EXIST` | 409 |
| `ERR_STORES_STILL_OPEN` | 409 |
| `ERR_BATCHES_NOT_DELIVERED` | 409 |
| `ERR_OPEN_SHIFTS_EXIST` | 409 |
| `ERR_RUN_NOT_COMPLETED` | 422 |
