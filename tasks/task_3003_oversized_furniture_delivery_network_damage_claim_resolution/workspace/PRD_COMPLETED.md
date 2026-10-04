# Oversize Freight Network API — Product Requirements Document

## 1. Introduction

Moving a sectional sofa from a supplier's warehouse to a customer's living room is an operationally different problem from shipping a book. Items must be cubed and classified into freight bands at the moment they are listed; every order must be routed among parcel carriers, less-than-truckload lanes, and the company's own final-mile hub network; delivery promises must absorb linehaul misses gracefully; and when a leg of the journey goes wrong, someone — the supplier or the carrier — has to pay for it. This document specifies the Oversize Freight Network API, the backbone that coordinates all of it.

The API governs the full commercial and physical lifecycle of a single-item oversized order: item listing with cubing and parcel-gate checks, order placement with constraint-propagation routing and a pinned fee split, linehaul planning and capacity management into destination hubs, appointment scheduling with room-of-choice crew conflict control, damage claim inspection and liability determination, supplier chargeback adjudication with a dispute-and-reversal path, and return authorization economics that decide whether an item is worth hauling back at all. Supplier behavior is scored continuously — a rolling on-time ship rate and a chargeback rate combine into a compliance score that can automatically place a supplier on probation, suspend them, or restore them to good standing without any human touching the record.

Because the domain mixes money, capacity, and time, several guarantees are load-bearing and non-negotiable: every fee and clawback is computed in integer cents with pinned evaluation order, every state transition cascades to the entities it affects, and a server-managed logical clock — never the wall clock — anchors promised dates, return windows, and expiry so that outcomes are deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, conventions, and cross-cutting principles that apply to every endpoint and every resource in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request carries `X-User-ID` identifying the acting user and `X-User-Role` naming their operational capacity. The system recognizes exactly six roles: `NetworkAdmin`, `Customer`, `HubOperator`, `ClaimsAdjuster`, `SupplierRep`, and `CarrierRep`. A request whose headers are missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the named role is not permitted to perform the requested operation — or when a `SupplierRep` attempts to act on a chargeback belonging to a different supplier — the request is rejected with `ERR_FORBIDDEN` (HTTP 403). A role value outside the six recognized roles is treated as not permitted for every endpoint and is likewise rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role, and the server interprets it differently for identity-backed versus opaque roles:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; where an ownership check applies to a resource that references a `Customer`, it compares the resource's `customer_id` foreign key to `X-User-ID`. In this API no endpoint actually performs a customer-ownership comparison — role membership alone gates access, so a `Customer` may read or act on any customer's resources where the endpoint table admits the role.
- When `X-User-Role` is `SupplierRep`, `X-User-ID` is the `id` of the acting `Supplier` record; the one ownership check that exists — the dispute operation on a chargeback — compares the resource's `supplier_id` foreign key to `X-User-ID`.
- When `X-User-Role` is `NetworkAdmin`, `HubOperator`, `ClaimsAdjuster`, or `CarrierRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for auditing, but it is never compared against any entity's `id`.

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
- Requests to paths the API does not define (unknown routes and wrong HTTP methods alike) are rejected in this same envelope with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100 — a `limit` that is not an integer or falls outside that range is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter specifies the number of items to skip and defaults to 0; a non-integer or negative `offset` is likewise rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by the resource's `id` in ascending string order. List endpoints additionally accept exact-match filter query parameters: `status` for suppliers; `supplier_id`, `freight_class`, and `status` for items; `leg_mode`, `dest_zone`, and `status` for freight lanes; `customer_id`, `item_id`, and `order_state` for orders; `order_id`, `hub_id`, `supplier_id`, `linehaul_id`, `item_id`, and `current_state` for shipments; `hub_id` and `status` for linehauls; `shipment_id`, `hub_id`, and `status` for appointments; `shipment_id` and `status` for damage claims; `supplier_id`, `damage_claim_id`, `shipment_id`, and `status` for chargebacks; and `order_id` and `status` for return authorizations. Supplying a value outside the declared enum set for an enum-typed filter is rejected with `ERR_INVALID_REQUEST`.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. `total_count` counts the full filtered result set before pagination, and `has_more` is true exactly when `offset + limit < total_count`.

### 2.4. Common Resource Properties

All resources in the system — Suppliers, Items, Hubs, Customers, Orders, FreightLanes, Shipments, Linehauls, DeliveryAppointments, DamageClaims, Chargebacks, and ReturnAuthorizations — carry a standard set of system-managed fields:

- `id` (string): a unique, system-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-09-01T10:30:00.123Z`), set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, and which serves as the basis for optimistic concurrency control where a rule requires it.

Any mutation of a resource — including the recomputation of a derived field such as a supplier's `compliance_score`, a shipment's `promised_date`, or a linehaul's `committed_count` — updates that resource's `updated_at` and increments its `version`, even when the mutation is performed automatically by the system rather than requested by a client.

### 2.5. The Logical Clock

Time inside this system is deterministic. The server maintains a logical clock whose value at startup is exactly `2026-09-01T00:00:00Z`, and the clock must never fall back to wall-clock time. All time-dependent rules — promised date computation, the 45-day return approval window, the 30-day return expiry, appointment window validation against "now", and `delivered_at`/`approved_at`/`actual_ship_date` stamping — read this logical clock. A `NetworkAdmin`-only test-driving capability sets the logical clock to a supplied `current_utc` instant — it accepts any valid ISO 8601 datetime, earlier or later than the current value, so scenarios can also rewind time — and responds `200 OK` with `{"current_utc": <the new value>}`. This capability exists so that date arithmetic across the whole API is reproducible. Date-bearing fields split into two representations: `promised_date`, `promised_ship_date`, `actual_ship_date`, `planned_arrival_date`, and `origin_ship_date` are ISO calendar dates (`YYYY-MM-DD`), while `delivered_at`, `approved_at`, and all `created_at`/`updated_at` values are full ISO 8601 UTC timestamps with three fractional digits.

### 2.6. Monetary Values, Precision, and Rounding

All monetary values are represented as integer cents and all arithmetic on them is integer arithmetic. Where a calculation produces a fractional cent — percentage fees, per-pound rates against ceiled weights, clawback shares — the value is rounded to whole cents using round-half-up, applied at each individual step of the computation rather than once at the end. Score-type values (cube score, on-time rate, chargeback rate, compliance score) are held to exactly 2 decimal places, also with round-half-up rounding, and any downstream calculation that consumes a rate consumes the already-rounded 2-decimal value, never an unrounded intermediate.

### 2.7. Validation Order and Nested Resource Retrieval

Every incoming request passes through a fixed validation pipeline, and the order matters because the first failing check determines the error returned. The checks are evaluated in this sequence: first, the presence and non-emptiness of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); second, whether the declared role is authorized for the endpoint (`ERR_FORBIDDEN`); third, whether every path and body identifier resolves to an existing resource, validated left-to-right with path segments first and body fields in their declared input order (`ERR_NOT_FOUND`) — an identifier that is absent from the payload or not a string is looked up as-is and fails this resolution like any unknown identifier, except where §3 explicitly special-cases a field (notably `item_id` at order creation); fourth, whether required fields are present, well-typed, and carry enum values inside their declared sets (`ERR_INVALID_REQUEST`); fifth, whether the target entity is in a valid state for the requested transition (`ERR_INVALID_STATE`). Only after these five general gates pass do the endpoint-specific business rules run, and each business rule surfaces its own error code. For endpoints with several business rules, the relative priority of those rules is stated in §3 alongside the workflow they guard.

### 2.8. Optimistic Concurrency Control

Exactly one endpoint in the API is protected by optimistic concurrency control: booking a delivery appointment. A booking request must carry `expected_shipment_version`, a non-optional field whose value is the `version` of the target `Shipment` as the client last observed it. If the value does not match the shipment's current `version` — because another writer has booked or cancelled an appointment against the same shipment and thereby legitimately advanced its version — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412), and no appointment is created. No other endpoint accepts or requires a version field; clients must not send one elsewhere.

### 2.9. Cascading State and Counter Consistency

The network is a web of parent-child and cross-aggregate relationships, and the system keeps them aligned automatically rather than asking clients to repair them. When an order is cancelled before transit, its shipment is moved to `EXCEPTION` and the bound linehaul's `committed_count` is decremented to release the slot. When a linehaul is marked missed, every shipment still riding it is re-evaluated: its miss count increments, its promised date is recomputed, and it is re-bound to another trailer or unbound entirely. When a chargeback is settled or reversed, the supplier's `chargeback_rate` and `compliance_score` are recomputed immediately, and the recomputation can itself trigger an automatic supplier status transition. Deliveries, appointments, inspections, and return completions all propagate into the parallel order state dimensions as described in §3. These cascades are part of the API contract: a client that performs the triggering action observes all of the side effects in a single response cycle.

### 2.10. The Status Code Convention

Operations that create a new, stand-alone resource — registering a supplier, listing an item, registering a hub, defining a freight lane, registering a customer, placing an order, planning a linehaul, booking an appointment, opening a damage claim, or requesting a return authorization — return `201 Created`. Operations that act upon an existing resource — every state-transition action, every retrieval, and every list — return `200 OK`. The clock-setting capability likewise returns `200 OK`.

## 3. Business Logic & Workflows

### 3.1. Listing an Item: Cubing, Freight Class, and the Parcel Gate

Before anything can be ordered, a `NetworkAdmin` must register the participating suppliers and list the catalog. Registering a supplier records its `supplier_code` (expected unique across the network, e.g. `SUP-1001`; the server does not reject duplicates), its `legal_name`, a `drop_ship_enabled` flag stating whether the supplier may fulfill orders directly to customers, and an optional `lead_time_days` representing promised drop-ship handling days, which defaults to 3 when omitted and must be a non-negative integer (else `ERR_INVALID_REQUEST`). A newly registered supplier starts with its `status` field at `ACTIVE`, a `compliance_score` of 100.00, an `on_time_ship_rate` of 100.00, and a `chargeback_rate` of 0.00; all three numbers are recomputed continuously as the network operates.

Customers are registered by a `NetworkAdmin` before they can purchase: registration records a unique `email` (expected unique; the server does not reject duplicates), the customer's `full_name`, and the `destination_zone` (e.g. `ZONE_NE`) that later drives routing decisions for their orders.

Listing an item is a `NetworkAdmin` operation that records the fulfilling `supplier_id` (an absent, mistyped, or unknown `supplier_id` fails the gate three lookup and is rejected with `ERR_NOT_FOUND`), a unique `sku` (expected unique; the server does not reject duplicates), the three packaged dimensions `dim_length_in`, `dim_width_in`, and `dim_height_in` in inches (each strictly greater than zero), the packaged `weight_lb` in pounds (strictly greater than zero), the retail `declared_value_cents` used as the basis for damage and return economics (a non-negative integer, else `ERR_INVALID_REQUEST`), and a `white_glove_eligible` flag indicating whether the item may be sold with `ROOM_OF_CHOICE` service. At the moment of listing, three computations run and are stored on the item.

First, the item's `cube_score` is computed as a weighted blend of its shape: 0.45 times the longest of the three packaged dimensions, plus 0.30 times the cube root of the product of the three dimensions, plus 0.25 times the sum of the three dimensions — with the result rounded half-up to 2 decimal places. Second, the `freight_class` is derived from that score using a threshold ladder whose boundaries are inclusive on the lower class: a score of at most 40.00 yields `PARCEL_ELIGIBLE`; above 40.00 and at most 70.00 yields `LTL_250`; above 70.00 and at most 100.00 yields `LTL_150`; above 100.00 and at most 150.00 yields `LTL_125`; anything above 150.00 yields `LTL_92_5`. A score of exactly 40.00 is therefore `PARCEL_ELIGIBLE`. Third, the parcel gate: the `declared_girth_in` is computed by rounding each dimension up to a whole inch individually first and only then combining them — the ceiled length plus twice the sum of the ceiled width and the ceiled height. This per-dimension-then-combine order is pinned; rounding the combined expression instead would produce a different girth. The item's `parcel_ok` flag is true when the resulting `declared_girth_in` is at most 165 inches. A newly listed item starts in `LISTED` status.

An item remains orderable until a `NetworkAdmin` delists it. Delisting requires the item to currently be `LISTED` (otherwise `ERR_INVALID_STATE`), and it is refused with `ERR_ITEM_HAS_OPEN_SHIPMENTS` while any shipment referencing the item is still in `CREATED`, `TENDERED`, `IN_TRANSIT`, `AT_HUB`, or `OUT_FOR_DELIVERY`. A delisted item moves to `DELISTED` — a terminal state — and future orders against it are rejected with `ERR_ITEM_NOT_LISTED`.

### 3.2. Network Topology: Hubs, Lanes, and Linehauls

The final-mile network is administered by a `NetworkAdmin` through three kinds of reference data. A hub is registered with a unique `hub_code` (e.g. `HUB-NE-01`; expected unique — the server does not reject duplicates), a display `name`, a list `serves_zones` of destination zone identifiers the hub covers (e.g. `ZONE_NE`), a `white_glove_capable` flag indicating whether crews at the hub can perform `ROOM_OF_CHOICE` deliveries, and a `daily_capacity` — a non-negative integer (else `ERR_INVALID_REQUEST`) — expressing the maximum number of linehauls that may reach `ARRIVED` status at the hub on any single calendar date, counted as a whole-date aggregate. Hubs are created `ACTIVE` and may later be `INACTIVE`.

A freight lane is a rate-card entry defined by its `leg_mode` — exactly one of `PARCEL`, `LTL`, or `OWNED_FINAL_MILE` — the `dest_zone` it serves, a flat `base_rate_cents`, an additional `per_lb_rate_cents` charged per pound of item weight (with the weight rounded up to a whole pound before multiplying), and `transit_days`, the calendar transit days for the leg, which must be at least 1. Lanes are created `ACTIVE` and may become `INACTIVE`.

A linehaul is a planned trailer movement into a specific hub, registered with its destination `hub_id`, a `planned_arrival_date`, an `origin_ship_date` that must fall strictly before the planned arrival date, and a `capacity` in shipment slots — a non-negative integer (else `ERR_INVALID_REQUEST`); an `origin_ship_date` equal to or after the `planned_arrival_date` is likewise rejected with `ERR_INVALID_REQUEST`. A linehaul is created `PLANNED` with a `committed_count` of zero; `committed_count` is a derived counter equal to the number of shipments currently bound to the linehaul whose `current_state` is neither `DELIVERED` nor `EXCEPTION`. The shipment's `current_state` field is the single physical-state dimension of the shipment lifecycle (`CREATED` → `TENDERED` → `IN_TRANSIT` → `AT_HUB` → `OUT_FOR_DELIVERY` → `DELIVERED`, with `EXCEPTION` as the off-path terminal), distinct from the two parallel dimensions carried by the order itself. Planning a linehaul has one automatic side effect: any `OWNED_FINAL_MILE` shipments headed to that hub that were previously left unbound (because no trailer had capacity) immediately bind, processed in ascending order of the shipments' `created_at` (ties broken by shipment `id`), each shipment taking the best available `PLANNED` linehaul into the hub under the same selector used at order time — the earliest `planned_arrival_date` with free capacity, ties broken by the linehaul's `created_at` in ascending order. The chosen trailer is not necessarily the newly planned one: an earlier-planned linehaul whose capacity has since freed is equally eligible.

A `NetworkAdmin` marks a linehaul departed, moving it from `PLANNED` to `DEPARTED`; any other source state is rejected with `ERR_INVALID_STATE`. A `HubOperator` then marks it arrived or missed. Arrival moves the linehaul from `DEPARTED` to `ARRIVED` and is gated by the hub's daily capacity: if the number of linehauls already `ARRIVED` at the same hub with the same `planned_arrival_date` has reached the hub's `daily_capacity`, the arrival is rejected with `ERR_HUB_DAILY_CAPACITY_EXCEEDED`. A successful arrival moves every bound shipment that is still `IN_TRANSIT` to `AT_HUB`. Marking a linehaul missed — also from `DEPARTED` only — triggers the network's most elaborate cascade, covered in §3.5.

### 3.3. Placing an Order: Routing, Pricing, and the Fee Split

A `Customer` places an order with a payload naming the `customer_id`, the `item_id`, and the desired `service_level`, which is either `THRESHOLD` or `ROOM_OF_CHOICE`. Orders are single-item only. At order creation, an `item_id` that is absent from the payload or not a well-formed string is not a resolvable reference at all: the §2.7 gate three lookup does not fire for it, and the request is rejected by the gate four presence-and-type check with `ERR_INVALID_REQUEST`. A well-formed but unknown `item_id` still resolves through gate three and is rejected with `ERR_NOT_FOUND`. The `customer_id` field is not special-cased this way: an absent, mistyped, or unknown `customer_id` simply fails the gate three lookup and is rejected with `ERR_NOT_FOUND`. Before any routing begins, the order request passes the general gates of §2.7 and then the order-specific business checks, which run in a defined relative order: first the service-level check — `ROOM_OF_CHOICE` requires the item's `white_glove_eligible` to be true, else `ERR_SERVICE_LEVEL_NOT_AVAILABLE`; then the listing check — the item must be `LISTED` and its supplier must not be `SUSPENDED`, else `ERR_ITEM_NOT_LISTED`; then routability — some hub/lane combination must be able to serve the customer's zone for the chosen service level, else `ERR_NO_ROUTE`; and finally pricing — an `ACTIVE` freight lane must exist for the leg mode the routing decision selected, else `ERR_PRICING_UNAVAILABLE`.

Routing itself is a constraint-propagation decision whose branches are evaluated strictly in order, with the first matching branch winning. Branch one is parcel: if the item's `freight_class` is `PARCEL_ELIGIBLE`, its `parcel_ok` flag is true, and an `ACTIVE` `PARCEL` lane exists for the customer's `destination_zone`, the shipment's `fulfillment_mode` and `leg_mode` are both set to `PARCEL`, and the shipment carries no hub or linehaul binding. Branch two applies when the order's service level is `ROOM_OF_CHOICE`: the candidate set is every hub that is `ACTIVE`, lists the customer's `destination_zone` in its `serves_zones`, and is `white_glove_capable`; the selector chooses the candidate whose `OWNED_FINAL_MILE` lane to the zone has the fewest `transit_days`, breaking ties by the hub's `created_at` ascending — never by identifier. The lane supplies only the ranking key; it is never a candidacy condition — a hub is a candidate on its `ACTIVE` status, zone coverage, and (for this branch) white-glove capability alone, and when no `ACTIVE` `OWNED_FINAL_MILE` lane exists for the zone the selector still proceeds, treating the transit-days key as infinite for every candidate so the `created_at` tie-break alone decides. An empty candidate set is a `ERR_NO_ROUTE`. A selected branch-two shipment takes `fulfillment_mode` `OWNED_FINAL_MILE` with `leg_mode` `OWNED_FINAL_MILE`. Branch three is drop-ship: if the item's supplier has `drop_ship_enabled` and is currently `ACTIVE`, the shipment takes `fulfillment_mode` `DROP_SHIP` with `leg_mode` `LTL`, no hub binding, and its `promised_ship_date` is set to the order creation date plus the supplier's `lead_time_days`. Branch four is the LTL network fallback: the candidates are all `ACTIVE` hubs serving the zone, selected by the same transit-days-then-creation-time rule as branch two, with an empty set again producing `ERR_NO_ROUTE`; such a shipment takes `fulfillment_mode` `OWNED_FINAL_MILE` but is priced on an `LTL` leg mode.

Pricing follows routing. The `shipping_amount_cents` is taken from the `ACTIVE` freight lane matching the shipment's `leg_mode` and the customer's `destination_zone`: the lane's `base_rate_cents` plus its `per_lb_rate_cents` multiplied by the item's weight rounded up to a whole pound. If no such lane exists, the order fails with `ERR_PRICING_UNAVAILABLE` (HTTP 402).

The order's fee split is then computed with a pinned evaluation order that must not be rearranged. The `order_total_cents` is computed first, as the item's `declared_value_cents` plus the `shipping_amount_cents`, before any fee component exists. The `oversized_surcharge_cents` comes second: it is zero when the item's `freight_class` is `PARCEL_ELIGIBLE`, and otherwise 5% of the `order_total_cents` rounded half-up to whole cents. The `handling_fee_cents` comes third: 8% applied to the remainder after subtracting the surcharge from the total — that is, 8% of (`order_total_cents` minus `oversized_surcharge_cents`) — rounded half-up to whole cents. Computing the handling fee on the pre-surcharge total would produce different cents and is incorrect.

A successful order creation creates exactly one `Shipment` for the order. The shipment copies its `order_id`, `item_id`, and `supplier_id` from the order and item, records the routed `fulfillment_mode` and `leg_mode`, and is born already in `TENDERED` — the `CREATED` to `TENDERED` step is immediate. For `OWNED_FINAL_MILE` routing the shipment is bound to a linehaul: the selector picks a `PLANNED` linehaul into the routed hub whose `committed_count` is below its `capacity`, preferring the earliest `planned_arrival_date` and breaking ties by the linehaul's `created_at` ascending; if none exists, order creation fails with `ERR_LINEHAUL_CAPACITY_EXCEEDED`. Binding increments the linehaul's `committed_count` by one. The order itself moves from `PENDING` to `ROUTED` automatically as routing succeeds, and the shipment's `promised_date` (the order carries no `promised_date` field of its own — the promise lives on the shipment) is computed as the order creation date plus 2 handling days plus the selected lane's `transit_days`, plus 1 additional hub-dwell day when the `fulfillment_mode` is `OWNED_FINAL_MILE`. For drop-ship shipments, which skip the hub entirely, no dwell day is added and `promised_ship_date` is set as described above; for network shipments `promised_ship_date` stays null.

An order carries two parallel state dimensions that evolve independently. The commercial `order_state` runs `PENDING` → `ROUTED` → `IN_TRANSIT` → `OUT_FOR_DELIVERY` → `DELIVERED`, or terminates early at `CANCELLED`. The execution-oriented `fulfillment_state` runs `NONE` → `SCHEDULED` → `FULFILLED` → `RETURNED`, and may jump directly from `NONE` to `FULFILLED` when a parcel or drop-ship shipment delivers without any appointment ever existing.

Cancellation is available to the ordering `Customer` or a `NetworkAdmin`, but only while `order_state` is `PENDING` or `ROUTED` — a later-stage cancel is rejected with `ERR_INVALID_STATE`. Cancelling moves the order to `CANCELLED`, moves its shipment to `EXCEPTION`, clears the shipment's `linehaul_id` to null, decrements the bound linehaul's `committed_count` by one to release the slot, and leaves `fulfillment_state` at `NONE`.

### 3.4. Moving Freight: Departures, Arrivals, and Direct Deliveries

Once an order is `ROUTED`, physical movement is confirmed by carrier and supplier representatives. Departure confirmation — performed by a `CarrierRep` for network shipments or a `SupplierRep` confirming a drop-ship ship — requires the shipment to be in `TENDERED` (else `ERR_INVALID_STATE`); it stamps the shipment's `actual_ship_date` with the logical clock's current date, moves the shipment from `TENDERED` to `IN_TRANSIT`, and moves the order from `ROUTED` to `IN_TRANSIT`. The role-to-mode pairing is operational guidance, not an enforced rule: either role may confirm the departure of any `TENDERED` shipment.

From `IN_TRANSIT`, the path splits by fulfillment mode. Hub-bound shipments wait for their linehaul to arrive, at which point they move to `AT_HUB` as described in §3.2, and complete through the appointment workflow of §3.5. Parcel and drop-ship shipments instead take a direct delivery confirmation from a `CarrierRep` or `SupplierRep` (again, either role may confirm either mode): the shipment must be `IN_TRANSIT` and its `fulfillment_mode` must not be `OWNED_FINAL_MILE` — hub shipments deliver via appointment, and an attempt to direct-deliver one is rejected with `ERR_INVALID_STATE`. A successful direct delivery moves the shipment to `DELIVERED`, stamps `delivered_at` with the logical clock, moves the order to `DELIVERED`, moves `fulfillment_state` from `NONE` straight to `FULFILLED`, and — for drop-ship shipments — triggers recomputation of the supplier's `on_time_ship_rate` and `compliance_score` as defined in §3.7.

### 3.5. Linehaul Misses and the Appointment Workflow

The appointment workflow exists only for `OWNED_FINAL_MILE` shipments. Booking a delivery appointment is a shared capability of the `Customer` and the `HubOperator`, and it is the one OCC-guarded write in the system: the request must name the `shipment_id`, the desired `window_start` and `window_end`, a `crew_id` identifying the crew within the hub, and the `expected_shipment_version` per §2.8. The shipment must currently be `AT_HUB`, with one exception: a shipment that is `OUT_FOR_DELIVERY` because a prior appointment was recorded as `NO_SHOW` may be booked again — that is the replacement booking the no-show rule below allows. Booking against any other shipment state — or against an `OUT_FOR_DELIVERY` shipment with no `NO_SHOW` appointment — is rejected with `ERR_INVALID_STATE`, and a version mismatch is rejected with `ERR_STALE_VERSION`. Because `expected_shipment_version` is a required integer field, an absent or non-integer value is rejected with `ERR_INVALID_REQUEST` by the gate four check, before any state or version comparison runs.

Among the booking's business checks, the window validation runs before the overlap check, and the version comparison runs last of all — after the shipment-state gate, the window validation, and the overlap check. The window itself must satisfy three temporal conditions: `window_start` strictly before `window_end`, a duration of at least 2 hours, and a `window_start` that is not before the logical clock's current instant; any violation is rejected with `ERR_INVALID_APPOINTMENT_WINDOW`. Then, for `ROOM_OF_CHOICE` service, the new booking must not overlap any existing `BOOKED` appointment on the same (`hub_id`, `crew_id`) pair, where windows are half-open intervals — the start is inclusive and the end is exclusive — so a back-to-back booking whose start equals the previous window's end is allowed. An overlap is rejected with `ERR_APPOINTMENT_OVERLAP`.

A successful booking creates the appointment in `BOOKED` status with its `service_level` copied from the order — never supplied by the client — and its `hub_id` copied from the shipment's bound hub. Booking advances the shipment from `AT_HUB` to `OUT_FOR_DELIVERY`, advances the order's `order_state` from `IN_TRANSIT` to `OUT_FOR_DELIVERY`, moves the order's `fulfillment_state` from `NONE` to `SCHEDULED`, and increments the shipment's `version` by one — the increment is what makes a stale concurrent booking detectable.

From `BOOKED`, an appointment has three exits. A `HubOperator` completing the delivery moves the appointment to `COMPLETED`, the shipment to `DELIVERED` with `delivered_at` stamped from the logical clock, the order's `order_state` to `DELIVERED`, and `fulfillment_state` from `SCHEDULED` to `FULFILLED`; completion also triggers the supplier metrics recomputation of §3.7. A `HubOperator` recording a customer no-show moves the appointment to `NO_SHOW` while the shipment stays `OUT_FOR_DELIVERY`, and a replacement appointment may subsequently be booked. Either the `Customer` or a `HubOperator` may cancel a booked appointment, which moves it to `CANCELLED`, frees the crew window for future overlap checks, and returns the shipment from `OUT_FOR_DELIVERY` to `AT_HUB` for rebooking — the order's `order_state`, however, stays `OUT_FOR_DELIVERY`; appointment cancellation does not revert it. All three transitions require the appointment to currently be `BOOKED`, else `ERR_INVALID_STATE`.

When a `HubOperator` marks a departed linehaul missed, the network compensates automatically. For every shipment bound to that linehaul whose state is neither `DELIVERED` nor `EXCEPTION` — processed in ascending order of the shipments' `created_at`, ties broken by shipment `id`, for both the miss increment and the rebinding: the shipment's `linehaul_misses` counter increments by one, its `promised_date` is recomputed — the promised date slips by exactly 2 days per recorded miss, reflecting one day of rebooked linehaul slip and one day of additional hub dwell — and the shipment re-binds to the earliest-`planned_arrival_date` `PLANNED` linehaul into the same hub with free capacity, ties broken by `created_at` ascending. The rebinding decrements the old linehaul's `committed_count` by one and increments the new one by one. If no suitable linehaul exists, the shipment's `linehaul_id` is set to null until a suitable trailer is planned, at which point it binds automatically per §3.2. The linehaul itself moves to `MISSED`, a terminal state.

### 3.6. Damage Claims: Inspection, Triage, and Liability

Damage reporting begins when a `Customer` or a `HubOperator` opens a damage claim against a shipment, naming the `shipment_id`, the `claimant_role` — `CUSTOMER` or `HUB_INSPECTOR`, recording who first reported the damage — and the `concealment` classification, `CONCEALED` or `VISIBLE_AT_DELIVERY`, which later drives liability attribution. There is no shipment-state precondition at open time: a claim may be opened against a shipment in any state, and inspectability is enforced later, at inspection. The claim is born `OPEN` with `damage_pct`, `is_structural`, `repair_cost_cents`, `resolution_type`, and `liability_party` all null and `chargeback_amount_cents` at 0, and its `replacement_cost_cents` is snapshotted from the item's `declared_value_cents` at creation time so later price changes cannot rewrite history. While `OPEN`, a claim may be withdrawn by the `Customer` or a `ClaimsAdjuster`, moving it to `WITHDRAWN`.

Inspection is performed by a `HubOperator` and requires two preconditions: the claim must be `OPEN` (else `ERR_INVALID_STATE`), and the shipment must be in `AT_HUB` or `DELIVERED` so there is something inspectable — otherwise `ERR_CLAIM_REQUIRES_INSPECTABLE_SHIPMENT`. The inspection records the `damage_pct` (an integer percentage from 0 to 100; a value outside that range is rejected with `ERR_INVALID_REQUEST`), the `is_structural` flag (true when frame or load-bearing damage is present), and the estimated `repair_cost_cents` (a non-negative integer, else `ERR_INVALID_REQUEST`), and it moves the claim to `INSPECTION` while computing its `resolution_type` by triage. The triage rule is evaluated in order: if the damage is structural, or the `damage_pct` is strictly greater than 40 — a reading of exactly 40 does not qualify — the resolution is `FULL_REPLACEMENT`; otherwise, if the `repair_cost_cents` exceeds the `replacement_cost_cents`, the resolution is also `FULL_REPLACEMENT`; otherwise, if the `repair_cost_cents` is at least 20000 cents, the resolution is `REPAIR`; anything cheaper resolves to `REPLACEMENT_PART`.

Liability determination is a `ClaimsAdjuster` action on an `INSPECTION` claim (any other state yields `ERR_INVALID_STATE`), moving it to `DETERMINATION` and allocating the loss by concealment class. When the claim is `CONCEALED`, the supplier is liable: the `liability_party` is set to `SUPPLIER`, the `chargeback_amount_cents` is the full repair cost plus 35% of the replacement cost, rounded half-up to whole cents, and a `Chargeback` is created in `PENDING` status with `amount_cents` equal to the claim's `chargeback_amount_cents`, linked one-to-one to the claim via `damage_claim_id` and carrying the debited `supplier_id`, the damaged `shipment_id`, and a `reason_code` of `CONCEALED_DAMAGE`, `REPAIR_OVERRUN`, or `FULL_REPLACEMENT` matching the resolution: a `REPLACEMENT_PART` resolution carries `CONCEALED_DAMAGE`, a `REPAIR` resolution carries `REPAIR_OVERRUN`, and a `FULL_REPLACEMENT` resolution carries `FULL_REPLACEMENT`. When the claim is `VISIBLE_AT_DELIVERY`, the carrier is liable: `liability_party` becomes `CARRIER`, the claim records only a 40%-of-repair-cost handling clawback as its `chargeback_amount_cents` (rounded half-up), and no `Chargeback` row is created at all. For `FULL_REPLACEMENT` resolutions, the replacement cost used in either variant is the snapshotted declared value regardless of the repair estimate.

Settlement, also by a `ClaimsAdjuster`, requires the claim to be in `DETERMINATION` and — when a linked chargeback exists — requires that chargeback to already be `SETTLED` or `REVERSED`; settling while the chargeback is still `PENDING` or `DISPUTED` is rejected with `ERR_CHARGEBACK_OPEN`. A settled claim moves to `SETTLED` and triggers recomputation of the supplier's `chargeback_rate` and `compliance_score`.

### 3.7. Chargebacks, Supplier Scoring, and Automatic Probation

A chargeback lives a short but contentious life: created `PENDING` at claim determination, it may be settled by a `NetworkAdmin`, disputed by the affected supplier's own `SupplierRep`, or — once disputed — reversed by a `NetworkAdmin`. Disputing is guarded twice: the acting `SupplierRep`'s `X-User-ID` must equal the chargeback's `supplier_id`, else `ERR_FORBIDDEN` — a supplier may never dispute another supplier's chargeback — and the chargeback must be `PENDING`, else `ERR_INVALID_STATE`. The ownership check runs first, consistent with the §2.7 pipeline, in which role-and-ownership authorization precedes the state gate. Settling works from either `PENDING` or `DISPUTED` and moves the chargeback to `SETTLED`; reversing works only from `DISPUTED` and moves it to `REVERSED`. Both settlement and reversal recompute the supplier's metrics, with reversal excluding `REVERSED` chargebacks from the rate.

Supplier scoring is a weighted blend maintained continuously. The `on_time_ship_rate` is the percentage, rounded half-up to 2 decimal places, of the supplier's 5 most recently closed — that is, `DELIVERED` — drop-ship shipments that departed on time (`actual_ship_date` on or before `promised_ship_date`); the window is ordered by `delivered_at` descending with ties broken by the shipment's `created_at` ascending, and a supplier with no closed shipments in the window holds 100.00. Because the window is rolling, old shipments age out of the denominator and a supplier's score can recover. The `chargeback_rate` is the percentage, also 2-decimal round-half-up, of `SETTLED` chargebacks attributed to the supplier over the count of the supplier's shipments whose state is not `EXCEPTION`; when the denominator is zero the rate is 0.00. The `compliance_score` blends the two: 0.60 times the on-time rate plus 0.40 times the complement of the chargeback rate (100 minus the chargeback rate), with the sum consuming the already-rounded 2-decimal rates and itself rounded half-up to 2 decimals.

The score drives automatic status transitions that require no human action. After any recomputation, a supplier in `ACTIVE` whose score falls below 70.00 moves to `PROBATION`, which removes its drop-ship routing eligibility (routing branch three requires an `ACTIVE` supplier). A supplier in `PROBATION` whose score falls below 50.00 moves to `SUSPENDED`, at which point new orders on that supplier's items are rejected with `ERR_ITEM_NOT_LISTED`. Recovery is symmetric but demanding: a `PROBATION` supplier whose score climbs back to at least 80.00 returns to `ACTIVE` and regains drop-ship eligibility. Note there is no automatic path out of `SUSPENDED`.

For reporting, a scorecard view exposes `on_time_ship_rate`, `chargeback_rate`, and `compliance_score` together with the `window` applied. The default window is `rolling` — the 5-shipment window above — while a `lifetime` window counts all closed drop-ship shipments; the two variants can therefore report different compliance scores for the same supplier once more than 5 shipments have closed, even with identical chargebacks. A `window` parameter value other than `rolling` or `lifetime` is rejected with `ERR_INVALID_REQUEST`.

### 3.8. Return Authorizations and Disposal Economics

A delivered order may be returned. A `Customer` requests a return authorization by naming the `order_id` and a `reason` — `DAMAGE`, `BUYERS_REMORSE`, or `WRONG_ITEM` — creating the authorization in `REQUESTED` with `reverse_haul_cost_cents`, `refurb_value_cents`, `disposition`, and `approved_at` all null until approval. Requesting imposes no precondition on the order's state; a return may be requested against an order at any stage, and the delivered check fires only at approval. A `NetworkAdmin` then approves or denies it. Denial requires the authorization to be `REQUESTED` (else `ERR_INVALID_STATE`) and simply moves the authorization to `DENIED`. Approval requires the authorization to be `REQUESTED` (else `ERR_INVALID_STATE`), the order's `order_state` to be `DELIVERED` with a recorded shipment `delivered_at` (else `ERR_ORDER_NOT_DELIVERED`), and the logical clock to be within 45 days of the order's delivery — the delivery timestamp plus exactly 45 days is still within the window, and only a clock reading strictly later than that is rejected with `ERR_RETURN_WINDOW_CLOSED`. Approval additionally requires an `ACTIVE` `LTL` lane to the customer's destination zone for the reverse-haul pricing below; if none exists the approval is rejected with `ERR_PRICING_UNAVAILABLE` (HTTP 402).

Approval is where the economics run. The `reverse_haul_cost_cents` is the `ACTIVE` `LTL` lane's `base_rate_cents` to the customer's zone multiplied by a 1.20 handling factor, rounded half-up to whole cents. The `refurb_value_cents` is a reason-driven fraction of the item's `declared_value_cents`, rounded half-up: 10% for `DAMAGE`, 40% for `BUYERS_REMORSE`, and 90% for `WRONG_ITEM`. The `disposition` compares the two: when the refurb value exceeds the reverse haul cost, the item comes back as `RETURN_TO_HUB`; otherwise — including an exact tie, where disposal wins at break-even — the disposition is `FIELD_DISPOSAL`. Approval stamps `approved_at` from the logical clock and moves the authorization to `APPROVED`.

From `APPROVED`, a `HubOperator` completes the return — completion requires the authorization to currently be `APPROVED`, else `ERR_INVALID_STATE` — moving the authorization to `COMPLETED` and the order's `fulfillment_state` from `FULFILLED` to `RETURNED`. Alternatively, if the logical clock passes 30 days past `approved_at` without completion, the authorization expires automatically, moving to `EXPIRED`: at exactly `approved_at` + 30 days the authorization is still `APPROVED`, and expiry fires only when the clock is strictly later. The expiry check is lazy — it is evaluated whenever the server handles a request, so the `EXPIRED` transition becomes observable on the first request processed after the deadline passes, and it carries the usual `updated_at` refresh and `version` increment.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or retrieve an existing resource return `200 OK`. All endpoints are mounted under the `/oversize-freight` prefix. Request payloads, preconditions, side effects, and the computations behind each action are specified in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/oversize-freight/suppliers` | Register a supplier | NetworkAdmin |
| GET | `/oversize-freight/suppliers` | List suppliers | NetworkAdmin, ClaimsAdjuster, SupplierRep |
| GET | `/oversize-freight/suppliers/{supplierId}` | Get one supplier | NetworkAdmin, ClaimsAdjuster, SupplierRep |
| GET | `/oversize-freight/suppliers/{supplierId}/scorecard` | Computed compliance scorecard; `window` selects the rolling (default) or lifetime variant | NetworkAdmin, ClaimsAdjuster, SupplierRep |
| POST | `/oversize-freight/items` | List an item (cubing, freight class, parcel gate computed at listing) | NetworkAdmin |
| GET | `/oversize-freight/items` | List items | NetworkAdmin, ClaimsAdjuster, SupplierRep, Customer |
| GET | `/oversize-freight/items/{itemId}` | Get one item | NetworkAdmin, ClaimsAdjuster, SupplierRep, Customer |
| POST | `/oversize-freight/items/{itemId}/delist` | Delist an item (blocked while open shipments reference it) | NetworkAdmin |
| POST | `/oversize-freight/hubs` | Register a final-mile hub | NetworkAdmin |
| GET | `/oversize-freight/hubs` | List hubs | NetworkAdmin, HubOperator, ClaimsAdjuster |
| GET | `/oversize-freight/hubs/{hubId}` | Get one hub | NetworkAdmin, HubOperator, ClaimsAdjuster |
| POST | `/oversize-freight/freight-lanes` | Create a freight lane (rate card entry) | NetworkAdmin |
| GET | `/oversize-freight/freight-lanes` | List freight lanes | NetworkAdmin, HubOperator |
| GET | `/oversize-freight/freight-lanes/{laneId}` | Get one freight lane | NetworkAdmin, HubOperator |
| POST | `/oversize-freight/customers` | Register a customer | NetworkAdmin |
| GET | `/oversize-freight/customers/{customerId}` | Get one customer | NetworkAdmin, Customer |
| POST | `/oversize-freight/orders` | Place a single-item order; routing, pricing, and fee split computed immediately | Customer |
| GET | `/oversize-freight/orders` | List orders | NetworkAdmin, Customer, HubOperator, ClaimsAdjuster |
| GET | `/oversize-freight/orders/{orderId}` | Get one order (both parallel state dimensions) | NetworkAdmin, Customer, HubOperator, ClaimsAdjuster |
| POST | `/oversize-freight/orders/{orderId}/cancel` | Cancel an order before transit | Customer, NetworkAdmin |
| GET | `/oversize-freight/shipments` | List shipments | NetworkAdmin, HubOperator, ClaimsAdjuster, SupplierRep |
| GET | `/oversize-freight/shipments/{shipmentId}` | Get one shipment | NetworkAdmin, HubOperator, ClaimsAdjuster, SupplierRep, Customer |
| POST | `/oversize-freight/shipments/{shipmentId}/depart` | Confirm departure (linehaul left origin, or drop-ship ship confirm) | CarrierRep, SupplierRep |
| POST | `/oversize-freight/shipments/{shipmentId}/deliver` | Direct delivery confirmation for parcel and drop-ship shipments | CarrierRep, SupplierRep |
| POST | `/oversize-freight/linehauls` | Plan a linehaul trailer into a hub | NetworkAdmin |
| GET | `/oversize-freight/linehauls` | List linehauls | NetworkAdmin, HubOperator |
| GET | `/oversize-freight/linehauls/{linehaulId}` | Get one linehaul | NetworkAdmin, HubOperator |
| POST | `/oversize-freight/linehauls/{linehaulId}/depart` | Mark linehaul departed origin | NetworkAdmin |
| POST | `/oversize-freight/linehauls/{linehaulId}/arrive` | Mark linehaul arrived at hub (gated on hub daily capacity) | HubOperator |
| POST | `/oversize-freight/linehauls/{linehaulId}/mark-missed` | Mark a departed linehaul missed; recompute promised dates and rebind shipments | HubOperator |
| POST | `/oversize-freight/appointments` | Book a delivery appointment (OCC-guarded on the shipment's version) | Customer, HubOperator |
| GET | `/oversize-freight/appointments` | List appointments | NetworkAdmin, HubOperator, Customer |
| GET | `/oversize-freight/appointments/{appointmentId}` | Get one appointment | NetworkAdmin, HubOperator, Customer |
| POST | `/oversize-freight/appointments/{appointmentId}/complete` | Complete delivery | HubOperator |
| POST | `/oversize-freight/appointments/{appointmentId}/mark-no-show` | Customer no-show | HubOperator |
| POST | `/oversize-freight/appointments/{appointmentId}/cancel` | Cancel a booked appointment; frees the crew window | Customer, HubOperator |
| POST | `/oversize-freight/damage-claims` | Open a damage claim against a shipment | Customer, HubOperator |
| GET | `/oversize-freight/damage-claims` | List damage claims | NetworkAdmin, ClaimsAdjuster, HubOperator, Customer |
| GET | `/oversize-freight/damage-claims/{claimId}` | Get one damage claim | NetworkAdmin, ClaimsAdjuster, HubOperator, Customer |
| POST | `/oversize-freight/damage-claims/{claimId}/inspect` | Record hub inspection; computes the resolution type | HubOperator |
| POST | `/oversize-freight/damage-claims/{claimId}/determine` | Determine liability; creates a chargeback when the supplier is liable | ClaimsAdjuster |
| POST | `/oversize-freight/damage-claims/{claimId}/settle` | Settle claim (requires linked chargeback resolved first) | ClaimsAdjuster |
| POST | `/oversize-freight/damage-claims/{claimId}/withdraw` | Withdraw an open claim | Customer, ClaimsAdjuster |
| GET | `/oversize-freight/chargebacks` | List chargebacks | NetworkAdmin, ClaimsAdjuster, SupplierRep |
| GET | `/oversize-freight/chargebacks/{chargebackId}` | Get one chargeback | NetworkAdmin, ClaimsAdjuster, SupplierRep |
| POST | `/oversize-freight/chargebacks/{chargebackId}/settle` | Settle a chargeback (debits supplier metrics) | NetworkAdmin |
| POST | `/oversize-freight/chargebacks/{chargebackId}/dispute` | Supplier disputes a pending chargeback (own chargebacks only) | SupplierRep |
| POST | `/oversize-freight/chargebacks/{chargebackId}/reverse` | Reverse a disputed chargeback | NetworkAdmin |
| POST | `/oversize-freight/return-authorizations` | Request a return authorization | Customer |
| GET | `/oversize-freight/return-authorizations` | List return authorizations | NetworkAdmin, HubOperator, Customer |
| GET | `/oversize-freight/return-authorizations/{raId}` | Get one return authorization | NetworkAdmin, HubOperator, Customer |
| POST | `/oversize-freight/return-authorizations/{raId}/approve` | Approve; computes disposal-versus-reverse-haul economics | NetworkAdmin |
| POST | `/oversize-freight/return-authorizations/{raId}/deny` | Deny a requested return | NetworkAdmin |
| POST | `/oversize-freight/return-authorizations/{raId}/complete` | Complete an approved return | HubOperator |
| POST | `/oversize-freight/_clock/set_current_utc` | Set the logical clock (startup default `2026-09-01T00:00:00Z`; never wall clock) | NetworkAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 principles and §3 workflows where the error arises; the table below is a reference of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SERVICE_LEVEL_NOT_AVAILABLE` | 422 |
| `ERR_ITEM_NOT_LISTED` | 409 |
| `ERR_NO_ROUTE` | 422 |
| `ERR_PRICING_UNAVAILABLE` | 402 |
| `ERR_INVALID_APPOINTMENT_WINDOW` | 422 |
| `ERR_APPOINTMENT_OVERLAP` | 409 |
| `ERR_HUB_DAILY_CAPACITY_EXCEEDED` | 409 |
| `ERR_LINEHAUL_CAPACITY_EXCEEDED` | 409 |
| `ERR_RETURN_WINDOW_CLOSED` | 422 |
| `ERR_CHARGEBACK_OPEN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ITEM_HAS_OPEN_SHIPMENTS` | 409 |
| `ERR_ORDER_NOT_DELIVERED` | 409 |
| `ERR_CLAIM_REQUIRES_INSPECTABLE_SHIPMENT` | 409 |
