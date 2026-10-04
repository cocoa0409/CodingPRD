# Delivery Point Sequencing, Route Adjustment & Service Standards API — Product Requirements Document

## 1. Introduction

Postal delivery operations rest on three pillars that are easy to state and difficult to enforce: every address in the country must be served, every route must reflect an honest accounting of the time it actually takes to walk or drive it, and every commitment made to a customer about when a piece of mail will arrive must be backed by a computable, auditable rule. This document specifies the Delivery Point Sequencing, Route Adjustment & Service Standards API, which is the operational system of record for those three pillars across a postal district.

The API governs the delivery point file that Address Management specialists maintain (new construction, occupancy and vacancy tracking, discontinuation), the line-of-travel sequencing and case setup that route supervisors produce for carriers, the periodic route evaluation and adjustment pipeline through which evaluated times are re-based against measured volume, and the service standard rule base that translates an origin/destination processing facility pair into a committed delivery date for each mail class. Woven through these workflows are obligations that do not yield to convenience: the universal service obligation forbids any operation that would strand a deliverable address without a route, segregation of duties forbids the supervisor who submits a route adjustment from approving it, and the consultation process guarantees the carrier a formal opportunity to dispute modeled street time before any adjustment is adopted.

The system also maintains the auxiliary assistance program for seasonal volume surges, the change-of-address and hold-mail subsystems that customers interact with at the retail window, and the delivery scan stream that feeds weekly compliance measurement against each unit's target. Every state change described here is atomic within the request that triggers it, and every mutation is versioned so that optimistic concurrency control can serialize conflicting writes.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven roles: `Anonymous`, `PlatformAdmin`, `AddressManagementSpecialist`, `RouteSupervisor`, `Postmaster`, `Carrier`, `CustomerServiceRep`, and `ServiceStandardsAdmin`. A request missing either header, or presenting an `X-User-Role` value that is not one of these declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). The `Anonymous` role exists only as the absence of credentials — it is authorized for no endpoint in this API; every operation requires one of the seven declared working roles.

Role identity semantics differ by role. When `X-User-Role` is `Carrier`, `X-User-ID` is the `id` of the acting `Carrier` record; the role is entity-backed, so ownership-style checks (for example, a carrier reading their own record) compare a resource's carrier foreign key to `X-User-ID`. For `PlatformAdmin`, `AddressManagementSpecialist`, `RouteSupervisor`, `Postmaster`, `CustomerServiceRep`, and `ServiceStandardsAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, a route adjustment records the submitting supervisor's id as `submitter_user_id` and the approving postmaster's id as `approver_user_id`, and the segregation-of-duties check compares those two recorded values — but the server does not compare `X-User-ID` to any entity's `id` for these roles.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Date-Driven System Transitions

All date-sensitive behavior in this API is evaluated against a single logical clock, never the host wall clock. Before any test-driving call, the logical clock reads exactly `2026-09-01T00:00:00Z` (the startup default). An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the new `current_utc` together with a count `transitions_fired` of the automatic transitions that fired as a result.

Advancing the logical clock is the single trigger for every date-driven transition in the system: a `PENDING` change-of-address whose `begin_date` has been reached moves to `ACTIVE`; an `ACTIVE` temporary forwarding order whose `end_date` has passed, or a permanent order twelve months past its `begin_date`, moves to `EXPIRED`; a `SCHEDULED` hold-mail window whose `hold_start_date` has been reached moves to `ACTIVE`, and an `ACTIVE` hold whose `hold_end_date` has passed moves to `EXPIRED`; an `APPROVED` route adjustment whose `effective_date` has been reached fires its full adoption cascade and becomes `EFFECTIVE`; an `APPROVED` auxiliary assignment whose `service_date` has been reached moves to `ACTIVE`; a customer inquiry with no status change for thirty days is closed as `CLOSED_ABANDONED`; and vacancy-day counters on every delivery point are recomputed against the new logical date. The same recomputation also happens on any read of a delivery point, so `vacancy_days` is always current as of the logical clock.

### 2.5. The Universal Service Obligation

Every `DeliveryUnit` carries the `universal_service_obligation` flag, which is always `true`, is set by the system at unit creation, and is immutable thereafter. The flag expresses the postal mandate that every active address receives delivery regardless of mail volume. The obligation has three operational teeth. First, no operation may leave a deliverable delivery point without a route assignment: suspending a route requires its `active_delivery_point_count` to be zero, and any operation that would strand a deliverable address is rejected with `ERR_USO_VIOLATION` (HTTP 422). This check applies to route suspension, point discontinuation, and adjustment approval. Second, non-deliverable does not mean unserved — a point whose `is_deliverable` is false still has its forwarding and hold-mail obligations honored. Third, when a point is discontinued, any customer inquiries still open against it remain open; the inquiry obligation survives the point itself.

### 2.6. Segregation of Duties in Route Adjustment

Route evaluation and route adjustment follow a strict maker-checker separation. A `RouteSupervisor` authors and submits an adjustment; only a `Postmaster` may approve or reject it; and the approving `X-User-ID` must differ from the `submitter_user_id` recorded at submission. A matching approver is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The same prohibition applies symmetrically to rejection: the postmaster who rejects an adjustment may not be the supervisor who submitted it. The two identifiers are recorded on the adjustment for audit.

### 2.7. Optimistic Concurrency Control

Three write endpoints are guarded by optimistic concurrency control against the parent resource they mutate. Every OCC-guarded request must carry a non-optional body field naming the client's last-observed version of the parent; if that value does not match the parent's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The three guarded endpoints and their required fields are:

- Replacing a route's full line-of-travel sequence requires `expected_route_version` matching the current `version` of the parent `CarrierRoute`. A mismatch means another writer has committed a new sequence that supersedes the client's intended ordering, and the write is rejected with `ERR_STALE_VERSION`.
- Opening a route evaluation requires `expected_route_version` matching the current `version` of the parent `CarrierRoute`. Creating an evaluation is a superseding declaration about the route's current state; a stale base means the client evaluated an out-of-date picture of point counts and times, and the write is rejected with `ERR_STALE_VERSION`.
- Creating a service standard rule requires `expected_facility_version` matching the current `version` of the parent origin `ProcessingFacility`. A concurrently landed rule change (a retirement or a new overlapping window) legitimately supersedes the client's intended window arithmetic, and the write is rejected with `ERR_STALE_VERSION`.

Endpoints not listed here do not take a version field.

### 2.8. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers — for example a unit, then a route, then an evaluation, then an adjustment — the system validates the existence and parentage of each identifier in sequential, left-to-right order. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist or does not belong to its declared parent, before any later segment or business rule is examined. The path parameter names used across the API are `unitId` for a delivery unit, `facilityId` for a processing facility, `ruleId` for a service standard rule, `queryId` for a service standard query, `pointId` for a delivery point, `carrierId` for a carrier, `routeId` for a carrier route, `entryId` for a sequence entry, `evalId` for a route evaluation, `adjId` for a route adjustment, `auxId` for an auxiliary assignment, `coaId` for a change-of-address order, `holdId` for a hold-mail window, `eventId` for a scan event, and `inquiryId` for a customer inquiry.

### 2.9. Validation Ordering

When a request could violate several rules at once, checks are evaluated in a fixed priority order so the error surfaced is deterministic. Authentication (401) comes first, then role authorization (403), then path existence left-to-right (404), then body-supplied foreign-key existence (`ERR_REFERENCE_NOT_FOUND`, 422), then state preconditions on the target (`ERR_INVALID_STATE`, 409 — with the terminal-state refinement below), then the optimistic concurrency check (`ERR_STALE_VERSION`, 412), then universal-service-obligation safety (422), then segregation of duties (403), then cross-entity state gates (`ERR_CROSS_ENTITY_STATE`, 409), then temporal windows (`ERR_TEMPORAL_WINDOW`, 422), then window overlap (`ERR_WINDOW_OVERLAP`, 409), then sequence integrity (`ERR_SEQUENCE_INVALID` / `ERR_SEQUENCE_DUPLICATE_POSITION`), then case capacity (`ERR_CASE_CAPACITY_EXCEEDED`), then numeric ranges (`ERR_RANGE_VIOLATION`), then auxiliary and vacancy thresholds (`ERR_OVERRUN_BELOW_THRESHOLD`), then service-rule coverage (`ERR_NO_SERVICE_RULE`), then uniqueness (`ERR_DUPLICATE_KEY`, 409), then request well-formedness (`ERR_INVALID_REQUEST`, 400), then the re-collection loop guard (`ERR_RECOLLECTION_EXHAUSTED`, 409), and finally the terminal-state refinement: when the target of a state-transition endpoint is already in a terminal state, the rejection is `ERR_ALREADY_TERMINAL` (HTTP 409) rather than the generic `ERR_INVALID_STATE`. Terminal states are `DISCONTINUED` for a delivery point; `EXPIRED` and `CANCELLED` for a change-of-address; `EFFECTIVE`, `REJECTED`, and `WITHDRAWN` for an adjustment; `CLOSED_ADOPTED` and `CLOSED_REJECTED` for an evaluation; `CLOSED_ABANDONED` and `RESOLVED_FINAL` for an inquiry; `COMPLETED`, `CURTAILED`, and `DENIED` for an auxiliary assignment; `RETIRED` for a service standard rule; and `EXPIRED`, `COMPLETED`, and `CANCELLED` for a hold-mail window.

### 2.10. Common Resource Properties

All primary resources include a standard set of system-managed fields:

- `id` (string): a unique, system-generated UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): a system-managed counter that increments by exactly one on every mutation of the resource, including mutations caused by cascade side effects originating elsewhere.

Two resource kinds are append-only or computed-read records and carry only `id` and `created_at` — both `updated_at` and `version` are absent: a `ServiceStandardQuery` (a persisted computed read) and a `DeliveryScanEvent` (an append-only scan record). All other entities carry the full common set.

### 2.11. Numeric Precision and Rounding

Intermediate monetary-free but precision-sensitive arithmetic in this API uses decimal arithmetic throughout. Calculations that specify two-decimal intermediates round each intermediate half-up to two decimal places before combining; final integer results are rounded half-up to whole numbers. Rates and fractions exposed to clients (notably the weekly scan compliance rate and each unit's `scan_compliance_target`) are represented as numbers with exactly four decimal places, rounded half-up. Dates are exact to the day with no rounding. The rounding order pinned by each calculation in §3 is part of the contract: reordering round-then-sum into sum-then-round produces different integers and is non-conformant.

## 3. Business Logic & Workflows

### 3.1. Facilities and the Service Standard Rule Base

A `ServiceStandardsAdmin` maintains the plant-level reference data on which all delivery-date commitments rest. Creating a processing facility requires a `facility_code` — a three-letter plant code of uppercase letters, unique system-wide — along with a `facility_type` of `P_AND_DC`, `S_AND_DC`, `NDC`, or `ANEX`; a `region_class` of `CONTIGUOUS` or `NON_CONTIGUOUS` that later selects between the two service-standard variants; a `dispatch_cutoff_local` critical entry time expressed as a 24-hour `HH:MM` string in the facility's local time; and a non-empty `operating_days` subset of the weekday codes `MON` through `SUN`. New facilities enter with `status` set to `ACTIVE`; the alternative state `DECOMMISSIONED` marks a plant that no longer originates or receives commitments.

Against each origin facility, the administrator files service standard rules. A rule names its `dest_facility_id` (which must differ from the origin facility and must reference an `ACTIVE` plant), a `mail_class` of `FIRST_CLASS`, `PRIORITY`, `GROUND_ADVANTAGE`, `PERIODICALS`, or `MARKETING`, a committed `service_days` between 1 and 7 inclusive, an optional `non_contiguous_extra_days` between 0 and 10 inclusive (defaulting to 2), and an `effective_from` date with an optional inclusive `effective_to` — an absent `effective_to` means the window is open-ended, and a present one must be at least `effective_from`. Rules for the same origin, destination, and mail class triple may not have overlapping effective windows, and the boundary is strict: end-adjacency, where one rule's `effective_to` equals the next rule's `effective_from`, is itself a conflict, so a succeeding window must begin strictly after the predecessor's last day. A violation of this overlap check is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409). Creation is OCC-guarded on the origin facility's version via `expected_facility_version` as described in §2.7, and a successful creation bumps the facility's `version` and sets the rule's `status` to `SCHEDULED` — the rule flips itself to `ACTIVE` once `effective_from` is at or before the current logical date. Retiring a rule is allowed only from `ACTIVE`; retirement stamps `effective_to` as the day before the current logical date and moves the rule to its terminal `RETIRED` state.

### 3.2. Computing a Committed Delivery Date

Any operational role may ask the system, for an origin facility, destination facility, mail class, acceptance date, and local acceptance time, what delivery date the Postal Service commits to. The question is posed by creating a `ServiceStandardQuery` carrying `origin_facility_id`, `dest_facility_id`, `mail_class`, `acceptance_date`, and `acceptance_time_local`; the computation is performed at creation and its results — `committed_delivery_date`, `committed_service_days`, and `variant_used` — are persisted on the query row.

Rule selection gathers every rule whose origin, destination, and mail class match the query, whose `status` is `SCHEDULED` or `ACTIVE`, and whose effective window covers the `acceptance_date`. Exactly one rule must match: zero matches are rejected with `ERR_NO_SERVICE_RULE` (HTTP 422), and more than one is rejected with `ERR_RULE_OVERLAP_CONFLICT` (HTTP 409) — a defensive case that the creation-time overlap check should render unreachable. Variant selection then looks at the two endpoint facilities: if either has `region_class` equal to `NON_CONTIGUOUS`, the `NON_CONTIGUOUS` variant fires and the committed service days are the rule's `service_days` plus its `non_contiguous_extra_days`; otherwise the `CONTIGUOUS` variant fires and the base `service_days` is used as-is. `variant_used` records which branch fired.

Cutoff handling comes next. When `acceptance_time_local` is later than the origin facility's `dispatch_cutoff_local`, acceptance is treated as occurring on the next origin operating day: the acceptance date advances by one calendar day and then skips forward until it lands on a day present in the origin's `operating_days`. Finally the date roll counts the committed number of service days starting from the (possibly advanced) acceptance date, and the acceptance date itself is the first day counted: whenever it is a counting day it consumes one service day. Only days that appear in the origin facility's `operating_days` are counted; non-operating days are skipped and consume no service days. Sundays never count even if listed in `operating_days` — with one exception: for mail class `PRIORITY` under the `CONTIGUOUS` variant only, a Sunday does count. The day on which the count completes is the `committed_delivery_date`. No service days total may exceed 7 at rule creation time, and `non_contiguous_extra_days` may not exceed 10.

### 3.3. Delivery Units, Carriers, and Routes

A `PlatformAdmin` creates a delivery unit by supplying a system-wide unique `unit_code`, an `office_name`, the `delivery_office_facility_id` of the plant that governs the unit's outbound origin computations (which must reference an `ACTIVE` facility at creation time), a `case_slot_count_per_route` between 4 and 1000 describing the physical letter and flat case slots available per route, and optionally a `scan_compliance_target` — the required fraction of weekly delivery scans with a valid GPS/stop match, defaulting to 0.98, bounded between 0.5 and 1.0, and stored to four decimal places. The unit's `active_route_count`, a computed count of its routes whose status is `STANDARD`, `UNDER_EVALUATION`, or `UNDER_ADJUSTMENT`, starts at zero.

A `Postmaster` onboards carriers into a unit with a unique `employee_id` (an `E` followed by seven digits), a `full_name`, and a `carrier_class` of `REGULAR`, `CITY_ASSISTANT`, `RURAL`, or `AUXILIARY`. A carrier's `status` begins at `AVAILABLE` and moves through `ON_ROUTE`, `DETAILED`, and `INACTIVE` over their assignment lifecycle.

A `RouteSupervisor` creates a carrier route inside a unit with a `route_code` unique within that unit (for example `C012`), an `assigned_carrier_id` referencing a carrier of the same unit whose status is not `INACTIVE`, and a `route_type` of `CITY`, `RURAL`, or `HIGHWAY_CONTRACT`. New routes begin in `STANDARD` status with `current_evaluated_minutes` equal to the contractual 8-hour baseline carried in `base_evaluated_minutes` (fixed at 480 minutes), and `auxiliary_relief_minutes` at zero. Creation bumps the unit's `active_route_count` by one. The route also tracks `active_delivery_point_count`, the count of its delivery points whose occupancy is `OCCUPIED` or `SEASONAL`, and `under_evaluation_since`, the timestamp at which the route last entered `UNDER_EVALUATION` (null otherwise).

A `Postmaster` may suspend a route, but only when it is empty: suspension requires `active_delivery_point_count` to be zero, because the universal service obligation forbids stranding addresses; a violation is rejected with `ERR_USO_VIOLATION`. Suspending a route moves it `STANDARD → SUSPENDED`, curtails every open auxiliary assignment on it (any assignment in `REQUESTED`, `APPROVED`, or `ACTIVE` moves to `CURTAILED` and the route's `auxiliary_relief_minutes` returns to zero), and decrements the unit's `active_route_count`. `SUSPENDED` is a transitional lock rather than a terminal state: a `Postmaster` may reactivate the route by supplying an `assigned_carrier_id` naming an `AVAILABLE` carrier of the unit — the prior carrier may have been detailed away — which moves the route back to `STANDARD`, replaces its carrier, and restores the unit's `active_route_count`.

### 3.4. The Delivery Point File and Occupancy Tracking

`AddressManagementSpecialist` operators maintain the delivery point file. Creating a point requires `address_line1`, `city`, a two-letter uppercase `state_code`, an eleven-digit `zip11` delivery-point barcode key that is unique system-wide, and a `point_kind` of `RESIDENTIAL`, `BUSINESS`, `CENTRALIZED`, or `PO_BOX`; an optional `delivery_restriction` of `NONE` (the default), `BUSINESS_ONLY_HOURS`, `GATED_CODE_ON_FILE`, or `NO_SECURE_LOCATION` records any access limitation. New construction enters as `occupancy_status` `UNDER_CONSTRUCTION` with `active_route_id` null and `vacancy_days` zero; the point's `delivery_unit_id` comes from the creation path.

Activation moves a point `UNDER_CONSTRUCTION → OCCUPIED`: the specialist supplies a `route_id` belonging to the same unit, the point's `active_route_id` is set, the target route's `active_delivery_point_count` increases by one, and a sequence entry is appended to that route at the next line-of-travel position with its case slots recomputed. A `Carrier` who finds an address empty marks it `OCCUPIED → VACANT`, but only when no `ACTIVE` hold with disposition `CARRIER_PICKUP` exists for the point — such a hold means the customer picks up at the office and the address must not be declared vacant; the conflict is rejected with `ERR_HOLD_ACTIVE` (HTTP 409). Marking vacant stamps `vacant_since_date` with the current logical date, decrements the route's `active_delivery_point_count`, and recomputes `is_deliverable`. A specialist may mark an occupied point seasonal (`OCCUPIED → SEASONAL`), and may return either a `VACANT` or `SEASONAL` point to `OCCUPIED`; returning from vacancy clears `vacant_since_date`, increments the route's `active_delivery_point_count`, and — when the point's `vacancy_days` at the moment of the flip was at least 90 and a route evaluation is `INITIATED` on the route — the evaluation remains valid but is flagged with a recount note.

Vacancy aging runs continuously against the logical clock. While a point is `VACANT` with a non-null `vacant_since_date`, `vacancy_days` is the difference in calendar days between the current logical date and `vacant_since_date`; in every other occupancy state it is zero. Deliverability derives from occupancy: `is_deliverable` is true when the point is `OCCUPIED` or `SEASONAL`, and also while `VACANT` with `vacancy_days` strictly below 90; it is false for `UNDER_CONSTRUCTION`, for `DISCONTINUED`, and for a vacant point whose streak has reached 90 days. The same 90-day boundary appears twice with opposite inclusivity: reaching exactly 90 days makes `is_deliverable` false, and reaching exactly 90 days qualifies the point for discontinuation.

Discontinuation moves a point `VACANT → DISCONTINUED` and is the file's only terminal transition. It requires `vacancy_days` of at least 90 — a streak of 89 days is rejected with `ERR_OVERRUN_BELOW_THRESHOLD` (HTTP 422) — and it requires that no `ACTIVE` change-of-address forwards mail from the point; an active forwarding order blocks discontinuation with `ERR_FORWARD_ACTIVE` (HTTP 409). On discontinuation, the point's sequence entry is removed from its route and the route re-sequenced per the renumber cascade, the route's `active_delivery_point_count` is recomputed, and any pending customer inquiries for the point remain open under the universal service obligation.

### 3.5. Line-of-Travel Sequencing and Case Setup

A route's line-of-travel is expressed as its ordered set of `RouteSequenceEntry` rows, each tied to its owning route via `carrier_route_id`. A `RouteSupervisor` replaces the full sequence in one atomic commit, supplying `expected_route_version` (the OCC guard from §2.7) and an `entries` payload. Each entry names a `delivery_point_id`, its one-based `line_of_travel_order` position, and a `delivery_order_group` of `PARK_LOOP` (the default), `MOUNTED`, `WALKING`, or `DISMOUNT`. Every referenced point must belong to this route — its `active_route_id` must already point here — and must be deliverable-eligible, meaning its occupancy is `OCCUPIED`, `SEASONAL`, or `VACANT`. The committed positions must form an exact permutation of 1 through N with no gaps; two entries claiming the same position are rejected with `ERR_SEQUENCE_DUPLICATE_POSITION` (HTTP 409), and other malformations or eligibility failures with `ERR_SEQUENCE_INVALID` (HTTP 422).

Case setup derives each entry's physical slot from its line-of-travel position using the unit's `case_slot_count_per_route` (call it S). The letter case slot of an entry is one plus the floor of its position-minus-one divided by two — adjacent odd/even positions share a letter slot row side. The flat case slot is one plus the floor of its position-minus-one divided by three — three line-of-travel positions map into each flat slot. The computed indexes are exposed on each entry as `case_slot_letters` and `case_slot_flats`. Capacity is enforced route-wide: if any entry's computed letter slot or flat slot exceeds S, the entire commit is rejected with `ERR_CASE_CAPACITY_EXCEEDED` (HTTP 422), and the check order is pinned — all letter slots for the whole route are validated first, then all flat slots, and only then does the atomic commit proceed. A successful commit also syncs each entry's point so its `active_route_id` references this route, and bumps the route's `version` by one.

Any mutation that changes the set of entries on a route — a point discontinuation, an adjustment's point transfers, or a full replace — triggers the renumber cascade: surviving entries are renumbered into a contiguous 1..N permutation preserving relative order (the caller-supplied order for a replace, the prior ascending order for removals). When an approved adjustment transfers points between two routes, the donor route is renumbered before the receiving route, and within the receiving route incoming points are appended in ascending order of their prior line-of-travel position on the donor; ties are broken by each point's `created_at` ascending, never by id.

### 3.6. Route Evaluation: Count, Consultation, and the Re-Collection Loop

Route evaluation is how the service re-bases a route's evaluated time against measured volume. A `RouteSupervisor` opens an evaluation by supplying an `evaluation_kind` of `FULL_COUNT`, `MINI_SURVEY`, or `SPECIAL_INSPECTION`, a `count_week_start` naming the first day of the six-day mail count (count weeks always run Saturday through Friday, so the date must be a Saturday), and `expected_route_version` for OCC. The route must be `STANDARD` — otherwise `ERR_CROSS_ENTITY_STATE` (HTTP 409) — and no other evaluation for the route may be open (one whose status is neither `CLOSED_ADOPTED` nor `CLOSED_REJECTED` blocks creation, rejected with `ERR_INVALID_STATE`); the open-evaluation check is applied before the optimistic concurrency check, so when both would fail the surfaced error is `ERR_INVALID_STATE`. Creation does not itself validate the Saturday or lead-time requirements of `count_week_start`; those are enforced when the count is begun. Opening the evaluation moves the route `STANDARD → UNDER_EVALUATION`, stamps `under_evaluation_since`, bumps the route's `version`, and creates the evaluation in `INITIATED` status with `consultation_outcome` `PENDING` and `recollection_used` false.

Beginning the count moves the evaluation `INITIATED → DATA_COLLECTION`. The Saturday requirement on `count_week_start` is enforced at this step for every evaluation kind, and for a `FULL_COUNT` evaluation there is an additional scheduling lead time: `count_week_start` must be at least 14 days in the future relative to the current logical date; violations are rejected with `ERR_TEMPORAL_WINDOW` (HTTP 422).

Once the count week is complete the supervisor submits the six count inputs — `letters_count_total`, `flats_count_total`, `parcels_count_total`, `actual_street_minutes_total`, and `office_minutes_total`, each a non-negative integer — moving the evaluation `DATA_COLLECTION → CONSULTATION_SCHEDULED` and triggering the modeled street time computation. The modeled value is computed in exactly this order, with per-step rounding. Casing minutes are the letters total divided by the casing rate of 18 letters per minute, rounded half-up to two decimals, plus the flats total divided by the flat casing rate of 8 flats per minute, rounded half-up to two decimals. Pull-down minutes are the combined letters-plus-flats total divided by 70, rounded half-up to two decimals. The street base is the parcels total multiplied by 2.5 minutes per parcel stop, rounded half-up to two decimals. A volume tier is then selected: when letters plus flats reach at least 12000 the tier is 2; otherwise when they reach at least 6000 the tier is 1; otherwise the tier is 0 — larger volumes amortize fixed street cost. The tier maps to a factor of 1.00, 0.97, or 0.94 respectively. The modeled street time is the weighted sum — street base, plus casing minutes times 0.62, plus pull-down minutes — multiplied by the tier factor, then rounded half-up to a whole number, and stored as `modeled_street_minutes_total`. The rounding order is fixed: each division rounds to two decimals first, then the weighted sum forms, then the final integer rounding; reordering into sum-then-round yields a different integer and is incorrect.

Consultation is the carrier's contractual check on the model. Recording the consultation moves the evaluation `CONSULTATION_SCHEDULED → CONSULTED` with a `consultation_outcome` of `CONCURRED`, `DISPUTED`, or `WAIVED`, and computes `evaluated_daily_minutes`. The adopted street time is a dual variant: when the outcome is `DISPUTED`, the adopted street time is the smaller of `actual_street_minutes_total` and `modeled_street_minutes_total` — a carrier-favorable floor; when the outcome is `CONCURRED` or `WAIVED`, the actual street time is adopted as-is. The evaluated daily minutes are then the office minutes plus the adopted street minutes, divided by six, rounded half-up to a whole number. The two variants diverge in whole minutes whenever the modeled value is lower than the actual and the outcome differs between `DISPUTED` and the concurrence branches.

When the carrier disputes, a `Postmaster` may order a re-collection, moving the evaluation `CONSULTED → DATA_COLLECTION`. The loop may fire at most once per evaluation: it requires the outcome to be `DISPUTED` and `recollection_used` still false, and firing it sets `recollection_used` true and zeroes the count inputs for re-entry — each of the five count inputs is reset to the integer `0` (they are declared non-negative integers), `modeled_street_minutes_total` and `evaluated_daily_minutes` are cleared, and `consultation_outcome` returns to `PENDING`. A second attempt, or an attempt without a disputed outcome, is rejected with `ERR_RECOLLECTION_EXHAUSTED` (HTTP 409).

If no adjustment will be pursued, the supervisor may close the evaluation `CONSULTED → CLOSED_REJECTED`, but only when no adjustment for this evaluation sits in `DRAFT`, `SUBMITTED`, or `APPROVED`; the route then bubbles back up to `STANDARD` with `under_evaluation_since` cleared, and the route's `version` increments. The remaining terminal state, `CLOSED_ADOPTED`, is reached only by the system when an approved adjustment goes effective, as described next.

### 3.7. Route Adjustment: Proposal, Approval, and the Effective-Date Cascade

Against an evaluation that has not reached a terminal state, a `RouteSupervisor` drafts a `RouteAdjustment` — tied to its parent evaluation through `route_evaluation_id` — with a `proposed_evaluated_minutes` between 240 and 600 inclusive (violations are `ERR_RANGE_VIOLATION`, HTTP 422), a possibly empty `points_transferred_out` list of moves each pairing a `delivery_point_id` with a `to_route_id`, and an `effective_date`. Drafting on an evaluation that is `CLOSED_ADOPTED` or `CLOSED_REJECTED` is rejected as a terminal-state violation; the `CONSULTED` requirement applies to submission, not drafting. Every destination route in the transfer list must belong to the same delivery unit, and no point may move to a `SUSPENDED` route. The adjustment begins in `DRAFT`. The supervisor may withdraw a draft, moving it `DRAFT → WITHDRAWN`.

Submitting moves the adjustment `DRAFT → SUBMITTED`; it requires the parent evaluation to be `CONSULTED` (otherwise `ERR_CROSS_ENTITY_STATE`) and records the acting supervisor's `X-User-ID` as `submitter_user_id` — the identifier that the segregation-of-duties rule will later exclude from approval. A `Postmaster` then approves or rejects. Approval moves `SUBMITTED → APPROVED`, requires the approver's `X-User-ID` to differ from `submitter_user_id` (a match is `ERR_SEGREGATION_OF_DUTIES`, HTTP 403), and requires the `effective_date` to be at least seven days after the current logical date (otherwise `ERR_TEMPORAL_WINDOW`). On approval the approver's id is recorded as `approver_user_id` and the route bubbles up `UNDER_EVALUATION → UNDER_ADJUSTMENT`. Rejection moves `SUBMITTED → REJECTED` under the same segregation constraint and leaves the parent evaluation in `CONSULTED`, so a replacement draft may be created.

The `APPROVED → EFFECTIVE` transition is system-driven: when the logical clock reaches the `effective_date`, the full adoption cascade fires atomically. The route's `current_evaluated_minutes` becomes the adjustment's `proposed_evaluated_minutes`, `under_evaluation_since` clears, the parent evaluation closes as `CLOSED_ADOPTED`, every transfer in `points_transferred_out` is applied — each point's `active_route_id` moves to its new route, both donor and receiving routes have their `active_delivery_point_count` recomputed, and both routes' sequence entries renumber per the cascade order in §3.5 — and the route returns `UNDER_ADJUSTMENT → STANDARD` with its `version` incremented. Until that cascade fires, an approved adjustment sits in `APPROVED` and the route remains under adjustment; the same protection applies throughout: no adjustment action is possible once the record reaches a terminal state.

### 3.8. Auxiliary Assistance and Seasonal Surges

When a route is projected to run long, a `RouteSupervisor` requests auxiliary assistance for a `service_date`, naming a `helper_carrier_id` and a `projected_overrun_minutes` — the minutes the route is expected to exceed its 480-minute baseline that day — and optionally setting `seasonal_surge_flag` true when the request is made under the seasonal surge program. The helper must be a carrier of the same unit whose `carrier_class` is `AUXILIARY` or `CITY_ASSISTANT`, and may not be the route's own `assigned_carrier_id`. The request enters as `REQUESTED`; `scheduled_minutes` is never client-supplied — it is computed at approval.

A `Postmaster` approves or denies. Approval requires the helper not be `INACTIVE` (else `ERR_CROSS_ENTITY_STATE`) and, when the surge flag is set, requires the current logical date to fall within the seasonal window running from November 15 through January 2 (else `ERR_TEMPORAL_WINDOW`). Approval computes the scheduled assistance in a fixed order. The projected overrun must be at least 30 minutes — below that floor no assistance is authorized and approval of such a request is rejected with `ERR_OVERRUN_BELOW_THRESHOLD`; an overrun of exactly 30 qualifies. The base assistance equals the projected overrun. Under the surge flag the base is multiplied by 1.25 and rounded half-up to whole minutes. If the route is already overburdened — its `current_evaluated_minutes` exceed its 480-minute `base_evaluated_minutes` — a fixed kicker of 15 minutes is added. The result is capped at a hard maximum of 240 minutes (four hours) per assignment, and stored as `scheduled_minutes`; the route's `auxiliary_relief_minutes` increases by that amount. Denial moves the request `REQUESTED → DENIED`.

On the `service_date` the assignment moves `APPROVED → ACTIVE` automatically and the helper carrier is treated as on-route for the day (a transient flag, not separately persisted). A `RouteSupervisor` then either completes the assignment (`ACTIVE → COMPLETED`) when the work is done or curtails it (`ACTIVE → CURTAILED`); both release the accrued relief by subtracting `scheduled_minutes` from the route's `auxiliary_relief_minutes`. Route suspension (§3.3) also curtails any open assignment on the route as a cascade.

### 3.9. Change-of-Address and Forwarding

A `CustomerServiceRep` files a change-of-address order against an originating unit, supplying the `old_delivery_point_id` mail is forwarded from, the destination `new_address_line1`, `new_city`, `new_state_code`, and eleven-digit `new_zip11` (which may lie outside the unit), a `move_kind` of `INDIVIDUAL`, `FAMILY`, or `BUSINESS`, a `move_type` of `PERMANENT` or `TEMPORARY`, and a `begin_date`. For a temporary move an `end_date` is required, must be later than `begin_date`, and may not extend more than 364 days past it; for a permanent move the `end_date` is null and the system enforces twelve-month forwarding for most classes. Temporal violations are rejected with `ERR_TEMPORAL_WINDOW`. An order may also carry `supersedes_coa_id`, chaining it to a prior order on the same old address that this one replaces; the referenced order must share the `old_delivery_point_id` and be in `PENDING` or `ACTIVE`. New orders begin with `forwarding_status` `PENDING` and `validation_status` `UNVERIFIED`.

Validation and forwarding are two independent dimensions. On the validation axis, the representative verifies (`UNVERIFIED → VERIFIED`) or rejects (`UNVERIFIED → REJECTED`) the order's address data. On the forwarding axis, activation — automatic when the logical clock reaches the `begin_date`, or forced same-day through an explicit activation action — requires the order to be `VERIFIED`; activating an unverified order is rejected with `ERR_CROSS_ENTITY_STATE`. Activation also enforces uniqueness of active forwarding per address: no other `ACTIVE` order may exist for the same old point, with one exception — when the other active order is exactly this order's supersession target, activation proceeds and the superseded order is automatically cancelled. Any other overlapping active order is rejected with `ERR_FORWARD_OVERLAP` (HTTP 409). When activation proceeds and an overlapping `ACTIVE` hold-mail window intersects the order's `[begin_date, end_date]` window, the hold remains active but forwarding takes precedence: mail forwards, and the hold is annotated — modeled as a side-effect flag only.

While `ACTIVE`, an order may be suspended and later resumed; resuming a temporary order past its `end_date` is not allowed. Expiry is automatic: a temporary order expires when the logical date passes its `end_date`, and a permanent order expires twelve months after its `begin_date`. Any order not yet terminal may be cancelled, moving it to `CANCELLED`.

### 3.10. Hold Mail

A `CustomerServiceRep` schedules a hold for a delivery point by supplying `delivery_point_id`, `hold_start_date`, `hold_end_date`, and a `disposition` of `ACCUMULATE_DELIVER_ON_END` or `CARRIER_PICKUP`. The start date may not be in the past relative to the current logical date, and the window may span at most 30 days inclusive — the end must be at least the start and no later than thirty days after it; violations are `ERR_TEMPORAL_WINDOW`. A new hold enters as `SCHEDULED`, and holds on the same point must not overlap: windows are compared as half-open intervals from the start date up to but not including the day after the end date, and an intersection — whether discovered at creation or at the moment a scheduled hold would activate — is rejected with `ERR_HOLD_OVERLAP` (HTTP 409).

Activation is automatic when the logical clock reaches `hold_start_date`, moving `SCHEDULED → ACTIVE`. Expiry is likewise automatic once the logical date passes `hold_end_date`, moving `ACTIVE → EXPIRED`; for a hold with disposition `ACCUMULATE_DELIVER_ON_END`, expiry implies a delivery action (modeled, with no further state). A `Carrier` honors a customer pickup by completing an active hold early (`ACTIVE → COMPLETED`); when the disposition is `CARRIER_PICKUP` no pickup scan is required — that fact is informational. A representative may cancel a hold from either `SCHEDULED` or `ACTIVE`, moving it to `CANCELLED`.

### 3.11. Delivery Scans and Weekly Compliance

Carriers record scan events against their routes. Each event names the `delivery_point_id` scanned, the scanning `carrier_id`, a `scan_code` of `DELIVERED`, `ATTEMPTED_NO_ACCESS`, `VACANT_CONFIRMED`, `FORWARDED`, `HELD_AT_OFFICE`, or `REFUSED`, an ISO 8601 UTC `scan_datetime`, and whether the device GPS sat within the point's geofence as `gps_within_geofence`. Because the `Carrier` role is entity-backed (§2.1), the `carrier_id` in the payload must equal the acting `X-User-ID`; a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403). Events are append-only. The system derives `is_compliant`: a scan is compliant only when `gps_within_geofence` is true and the scan code agrees with the point's occupancy — a `VACANT_CONFIRMED` scan requires the point to actually be `VACANT`, and a `DELIVERED` scan requires a deliverable point.

Weekly compliance is a computed read for the unit: given a `week_start`, the window is the half-open seven days beginning at `week_start`. The response reports `week_start`, `total_scans` (events on the unit's routes whose `scan_datetime` falls in the window), `compliant_scans` (those with `is_compliant` true), `compliance_rate`, and `meets_target`. The rate is the compliant count divided by the total, rounded half-up to four decimal places; an empty week reports a rate of 1.0 rather than 0.0 — a pinned policy choice. `meets_target` is true when the rate is at least the unit's `scan_compliance_target`, and the boundary is inclusive: a rate exactly equal to the target (for example 0.9800 against a target of 0.98) passes.

### 3.12. Customer Inquiries

A `CustomerServiceRep` opens an inquiry against a unit by naming the `delivery_point_id` concerned, an `inquiry_kind` of `MISSING_MAIL`, `LATE_DELIVERY`, `WRONG_DELIVERY`, `HOLD_NOT_HONORED`, or `FORWARD_NOT_RECEIVED`, the `opened_by_channel` of `PHONE`, `WEB`, or `WALK_IN`, and optionally a `related_scan_event_id` linking a specific scan. The inquiry opens in `OPEN` status with `reopened_count` zero and a computed `sla_due_datetime`: the open timestamp plus three business days on the unit's operating calendar, approximated as three 24-hour increments skipping Sundays.

Beginning investigation moves `OPEN → INVESTIGATING`. Resolution requires a `resolution_code` of `FOUND_AND_DELIVERED`, `SENDER_CONTACTED`, `FORWARD_CONFIRMED`, or `NO_ERROR_FOUND`, and branches on the loop counter: while `reopened_count` is below two, resolution lands in `RESOLVED`; once `reopened_count` has reached two, the third resolution instead lands in `RESOLVED_FINAL`, locking the inquiry. A resolved inquiry may be reopened — `RESOLVED → OPEN` — only within fourteen days of its resolution timestamp; a later attempt is rejected with `ERR_REOPEN_WINDOW_EXPIRED` (HTTP 422), and each reopen increments `reopened_count`. Inquiries that sit without any status change for thirty days are abandoned automatically as `CLOSED_ABANDONED` when the logical clock advances. As noted in §3.4, discontinuing a delivery point never closes its open inquiries.

## 4. Endpoint Definitions

All endpoints live under the `/api` mount. Creating a new resource returns HTTP 201; all other successful operations — modifications, state transitions, computed reads that persist a row notwithstanding (service standard queries return 201 as they persist), and pure reads — return HTTP 200. State-transition endpoints return the transitioned resource in `data`. All requests require the `X-User-ID` and `X-User-Role` headers described in §2.1.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Advance the logical clock; fires all date-driven system transitions | PlatformAdmin |
| POST | /api/processing-facilities | Create a processing facility | ServiceStandardsAdmin |
| GET | /api/processing-facilities/{facilityId} | Get a processing facility | ServiceStandardsAdmin, PlatformAdmin, RouteSupervisor, Postmaster, CustomerServiceRep |
| GET | /api/processing-facilities | List processing facilities with optional filters | ServiceStandardsAdmin, PlatformAdmin, RouteSupervisor, Postmaster, CustomerServiceRep |
| POST | /api/processing-facilities/{facilityId}/service-standard-rules | Create a service standard rule with this facility as origin (OCC-guarded) | ServiceStandardsAdmin |
| GET | /api/processing-facilities/{facilityId}/service-standard-rules | List rules whose origin is this facility | ServiceStandardsAdmin, PlatformAdmin, RouteSupervisor, Postmaster, CustomerServiceRep |
| GET | /api/processing-facilities/{facilityId}/service-standard-rules/{ruleId} | Get a rule scoped to its origin facility | ServiceStandardsAdmin, PlatformAdmin, RouteSupervisor, Postmaster, CustomerServiceRep |
| POST | /api/service-standard-rules/{ruleId}/retire | Retire a rule (sets `effective_to` to yesterday, status `RETIRED`) | ServiceStandardsAdmin |
| POST | /api/service-standard-queries | Compute and persist a committed delivery date for an origin/dest/class/acceptance tuple | ServiceStandardsAdmin, CustomerServiceRep, RouteSupervisor, Postmaster, PlatformAdmin |
| GET | /api/service-standard-queries/{queryId} | Get a previously computed query | ServiceStandardsAdmin, CustomerServiceRep, RouteSupervisor, Postmaster, PlatformAdmin |
| GET | /api/service-standard-queries | List computed queries with optional filters | ServiceStandardsAdmin, CustomerServiceRep, RouteSupervisor, Postmaster, PlatformAdmin |
| POST | /api/delivery-units | Create a delivery unit | PlatformAdmin |
| GET | /api/delivery-units/{unitId} | Get a delivery unit | PlatformAdmin, Postmaster, RouteSupervisor, AddressManagementSpecialist, CustomerServiceRep, Carrier |
| GET | /api/delivery-units | List delivery units | PlatformAdmin, Postmaster, RouteSupervisor, AddressManagementSpecialist, CustomerServiceRep |
| POST | /api/delivery-units/{unitId}/delivery-points | Create a delivery point (new construction) | AddressManagementSpecialist |
| GET | /api/delivery-units/{unitId}/delivery-points/{pointId} | Get a delivery point | AddressManagementSpecialist, RouteSupervisor, Postmaster, CustomerServiceRep, Carrier, PlatformAdmin |
| GET | /api/delivery-units/{unitId}/delivery-points | List points of a unit, filterable | AddressManagementSpecialist, RouteSupervisor, Postmaster, CustomerServiceRep, Carrier, PlatformAdmin |
| POST | /api/delivery-units/{unitId}/delivery-points/{pointId}/activate | Activate a new-construction point onto a route | AddressManagementSpecialist |
| POST | /api/delivery-units/{unitId}/delivery-points/{pointId}/mark-vacant | Carrier marks an occupied point vacant | Carrier |
| POST | /api/delivery-units/{unitId}/delivery-points/{pointId}/mark-occupied | Return a vacant or seasonal point to occupancy | AddressManagementSpecialist |
| POST | /api/delivery-units/{unitId}/delivery-points/{pointId}/mark-seasonal | Mark an occupied point seasonal | AddressManagementSpecialist |
| POST | /api/delivery-units/{unitId}/delivery-points/{pointId}/discontinue | Discontinue a long-vacant point | AddressManagementSpecialist |
| POST | /api/delivery-units/{unitId}/carriers | Create a carrier at the unit | Postmaster |
| GET | /api/delivery-units/{unitId}/carriers/{carrierId} | Get a carrier | Postmaster, RouteSupervisor, PlatformAdmin, Carrier |
| GET | /api/delivery-units/{unitId}/carriers | List carriers of a unit | Postmaster, RouteSupervisor, PlatformAdmin |
| POST | /api/delivery-units/{unitId}/routes | Create a carrier route | RouteSupervisor |
| GET | /api/delivery-units/{unitId}/routes/{routeId} | Get a route | RouteSupervisor, Postmaster, AddressManagementSpecialist, CustomerServiceRep, Carrier, PlatformAdmin |
| GET | /api/delivery-units/{unitId}/routes | List routes of a unit | RouteSupervisor, Postmaster, AddressManagementSpecialist, CustomerServiceRep, PlatformAdmin |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/suspend | Suspend an emptied route | Postmaster |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/reactivate | Reactivate a suspended route with a replacement carrier | Postmaster |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/sequence-entries | Atomically replace the route's full line-of-travel sequence (OCC-guarded) | RouteSupervisor |
| GET | /api/delivery-units/{unitId}/routes/{routeId}/sequence-entries | List sequence entries of a route ordered by line-of-travel | RouteSupervisor, Postmaster, AddressManagementSpecialist, Carrier, PlatformAdmin |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/evaluations | Open a route evaluation (OCC-guarded) | RouteSupervisor |
| GET | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId} | Get an evaluation | RouteSupervisor, Postmaster, PlatformAdmin |
| GET | /api/delivery-units/{unitId}/routes/{routeId}/evaluations | List evaluations of a route | RouteSupervisor, Postmaster, PlatformAdmin |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/begin-count | Begin the count week | RouteSupervisor |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/submit-counts | Submit count inputs; computes modeled street time | RouteSupervisor |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/record-consultation | Record consultation outcome; computes evaluated daily minutes | RouteSupervisor |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/order-recollection | Order a one-time re-collection on a disputed outcome | Postmaster |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/close-rejected | Close the evaluation without adoption | RouteSupervisor |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/adjustments | Create a draft adjustment on a non-terminal evaluation | RouteSupervisor |
| GET | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/adjustments | List adjustments of an evaluation | RouteSupervisor, Postmaster, PlatformAdmin |
| GET | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/adjustments/{adjId} | Get an adjustment | RouteSupervisor, Postmaster, PlatformAdmin |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/adjustments/{adjId}/submit | Submit a draft adjustment | RouteSupervisor |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/adjustments/{adjId}/approve | Approve a submitted adjustment (segregation of duties) | Postmaster |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/adjustments/{adjId}/reject | Reject a submitted adjustment | Postmaster |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/evaluations/{evalId}/adjustments/{adjId}/withdraw | Withdraw a draft adjustment | RouteSupervisor |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/auxiliary-assignments | Request auxiliary assistance for a route on a service date | RouteSupervisor |
| GET | /api/delivery-units/{unitId}/routes/{routeId}/auxiliary-assignments | List auxiliary assignments of a route | RouteSupervisor, Postmaster, PlatformAdmin |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/auxiliary-assignments/{auxId}/approve | Approve a request; computes scheduled minutes and accrues route relief | Postmaster |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/auxiliary-assignments/{auxId}/deny | Deny a request | Postmaster |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/auxiliary-assignments/{auxId}/complete | Complete an active assignment; releases route relief | RouteSupervisor |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/auxiliary-assignments/{auxId}/curtail | Curtail an active assignment; releases route relief | RouteSupervisor |
| POST | /api/delivery-units/{unitId}/coas | File a change-of-address / forwarding order | CustomerServiceRep |
| GET | /api/delivery-units/{unitId}/coas/{coaId} | Get a change-of-address order | CustomerServiceRep, Postmaster, PlatformAdmin |
| GET | /api/delivery-units/{unitId}/coas | List orders of a unit, filterable | CustomerServiceRep, Postmaster, PlatformAdmin |
| POST | /api/delivery-units/{unitId}/coas/{coaId}/verify | Verify the order's address data | CustomerServiceRep |
| POST | /api/delivery-units/{unitId}/coas/{coaId}/reject-validation | Reject the order's address data | CustomerServiceRep |
| POST | /api/delivery-units/{unitId}/coas/{coaId}/activate-now | Same-day activation; auto-cancels a superseded order | CustomerServiceRep |
| POST | /api/delivery-units/{unitId}/coas/{coaId}/suspend | Suspend an active order | CustomerServiceRep |
| POST | /api/delivery-units/{unitId}/coas/{coaId}/resume | Resume a suspended order | CustomerServiceRep |
| POST | /api/delivery-units/{unitId}/coas/{coaId}/cancel | Cancel any non-terminal order | CustomerServiceRep |
| POST | /api/delivery-units/{unitId}/holds | Schedule a hold-mail window for a delivery point | CustomerServiceRep |
| GET | /api/delivery-units/{unitId}/holds/{holdId} | Get a hold | CustomerServiceRep, Postmaster, Carrier, PlatformAdmin |
| GET | /api/delivery-units/{unitId}/holds | List holds of a unit, filterable by point | CustomerServiceRep, Postmaster, Carrier, PlatformAdmin |
| POST | /api/delivery-units/{unitId}/holds/{holdId}/complete-early | Carrier completes an active hold early | Carrier |
| POST | /api/delivery-units/{unitId}/holds/{holdId}/cancel | Cancel a scheduled or active hold | CustomerServiceRep |
| POST | /api/delivery-units/{unitId}/routes/{routeId}/scan-events | Record a delivery scan event (append-only) | Carrier |
| GET | /api/delivery-units/{unitId}/routes/{routeId}/scan-events | List scan events of a route | RouteSupervisor, Postmaster, CustomerServiceRep, PlatformAdmin |
| GET | /api/delivery-units/{unitId}/scan-compliance | Computed weekly scan compliance rate for the unit | RouteSupervisor, Postmaster, PlatformAdmin |
| POST | /api/delivery-units/{unitId}/inquiries | Open a customer inquiry | CustomerServiceRep |
| GET | /api/delivery-units/{unitId}/inquiries/{inquiryId} | Get an inquiry | CustomerServiceRep, Postmaster, PlatformAdmin |
| GET | /api/delivery-units/{unitId}/inquiries | List inquiries of a unit | CustomerServiceRep, Postmaster, PlatformAdmin |
| POST | /api/delivery-units/{unitId}/inquiries/{inquiryId}/begin-investigation | Begin investigating an open inquiry | CustomerServiceRep |
| POST | /api/delivery-units/{unitId}/inquiries/{inquiryId}/resolve | Resolve an investigating inquiry | CustomerServiceRep |
| POST | /api/delivery-units/{unitId}/inquiries/{inquiryId}/reopen | Reopen a resolved inquiry within the 14-day window | CustomerServiceRep |
| GET | /api/delivery-points | Filtered list of delivery points across units | AddressManagementSpecialist, RouteSupervisor, Postmaster, CustomerServiceRep, PlatformAdmin |
| GET | /api/delivery-points/{pointId} | Get a delivery point by id (flat form) | AddressManagementSpecialist, RouteSupervisor, Postmaster, CustomerServiceRep, Carrier, PlatformAdmin |
| GET | /api/carriers | Filtered list of carriers | Postmaster, RouteSupervisor, PlatformAdmin |
| GET | /api/carriers/{carrierId} | Get a carrier by id (flat form) | Postmaster, RouteSupervisor, PlatformAdmin, Carrier |
| GET | /api/routes | Filtered list of routes | RouteSupervisor, Postmaster, AddressManagementSpecialist, CustomerServiceRep, PlatformAdmin |
| GET | /api/routes/{routeId} | Get a route by id (flat form) | RouteSupervisor, Postmaster, AddressManagementSpecialist, CustomerServiceRep, Carrier, PlatformAdmin |
| GET | /api/sequence-entries | Filtered list of sequence entries | RouteSupervisor, Postmaster, AddressManagementSpecialist, PlatformAdmin |
| GET | /api/sequence-entries/{entryId} | Get a sequence entry by id (flat form) | RouteSupervisor, Postmaster, AddressManagementSpecialist, Carrier, PlatformAdmin |
| GET | /api/evaluations | Filtered list of route evaluations | RouteSupervisor, Postmaster, PlatformAdmin |
| GET | /api/evaluations/{evalId} | Get an evaluation by id (flat form) | RouteSupervisor, Postmaster, PlatformAdmin |
| GET | /api/adjustments | Filtered list of route adjustments | RouteSupervisor, Postmaster, PlatformAdmin |
| GET | /api/adjustments/{adjId} | Get an adjustment by id (flat form) | RouteSupervisor, Postmaster, PlatformAdmin |
| GET | /api/auxiliary-assignments | Filtered list of auxiliary assignments | RouteSupervisor, Postmaster, PlatformAdmin |
| GET | /api/auxiliary-assignments/{auxId} | Get an auxiliary assignment by id (flat form) | RouteSupervisor, Postmaster, PlatformAdmin |
| GET | /api/coas | Filtered list of change-of-address orders | CustomerServiceRep, Postmaster, PlatformAdmin |
| GET | /api/coas/{coaId} | Get a change-of-address order by id (flat form) | CustomerServiceRep, Postmaster, PlatformAdmin |
| GET | /api/holds | Filtered list of hold-mail windows | CustomerServiceRep, Postmaster, Carrier, PlatformAdmin |
| GET | /api/holds/{holdId} | Get a hold-mail window by id (flat form) | CustomerServiceRep, Postmaster, Carrier, PlatformAdmin |
| GET | /api/service-standard-rules | Filtered list of service standard rules | ServiceStandardsAdmin, PlatformAdmin, RouteSupervisor, Postmaster, CustomerServiceRep |
| GET | /api/service-standard-rules/{ruleId} | Get a service standard rule by id (flat form) | ServiceStandardsAdmin, PlatformAdmin, RouteSupervisor, Postmaster, CustomerServiceRep |
| GET | /api/scan-events | Filtered list of delivery scan events | RouteSupervisor, Postmaster, CustomerServiceRep, PlatformAdmin |
| GET | /api/scan-events/{eventId} | Get a scan event by id (flat form) | RouteSupervisor, Postmaster, CustomerServiceRep, PlatformAdmin |
| GET | /api/inquiries | Filtered list of customer inquiries | CustomerServiceRep, Postmaster, PlatformAdmin |
| GET | /api/inquiries/{inquiryId} | Get a customer inquiry by id (flat form) | CustomerServiceRep, Postmaster, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DUPLICATE_KEY | 409 |
| ERR_USO_VIOLATION | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_CROSS_ENTITY_STATE | 409 |
| ERR_TEMPORAL_WINDOW | 422 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_SEQUENCE_INVALID | 422 |
| ERR_SEQUENCE_DUPLICATE_POSITION | 409 |
| ERR_CASE_CAPACITY_EXCEEDED | 422 |
| ERR_RANGE_VIOLATION | 422 |
| ERR_OVERRUN_BELOW_THRESHOLD | 422 |
| ERR_NO_SERVICE_RULE | 422 |
| ERR_RULE_OVERLAP_CONFLICT | 409 |
| ERR_RECOLLECTION_EXHAUSTED | 409 |
| ERR_HOLD_ACTIVE | 409 |
| ERR_FORWARD_ACTIVE | 409 |
| ERR_FORWARD_OVERLAP | 409 |
| ERR_HOLD_OVERLAP | 409 |
| ERR_REOPEN_WINDOW_EXPIRED | 422 |
