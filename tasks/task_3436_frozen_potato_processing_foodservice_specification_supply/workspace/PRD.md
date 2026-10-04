# Frozen Potato Processing & Foodservice Specification Supply API — Product Requirements Document

## 1. Introduction

A frozen-potato processor lives and dies by coordination across a long, perishable pipeline: acreage is contracted with growers before planting, raw potatoes are held in controlled-atmosphere storage cells to stretch the processing season, lines cut, blanch, coat, and freeze against each chain customer's exact cut specification, and finished cases move through frozen cold chain to distributors and restaurant operators. This document specifies the API that governs that pipeline end to end — grower contracting with quality-based payment schedules, storage posture management, specification validation, capacity allocation, production execution, freight settlement, and the response protocol when the crop falls short.

Several mechanics define the system's character and appear throughout this document. A single plant-wide weekly case pool is reserved among chain customers by their supply agreements, and a shortage event reallocates that pool when supply collapses. Storage facilities carry a derived posture — `NORMAL`, `WATCH`, or `QUARANTINED` — that gates every movement of raw product as a food-safety isolation boundary. A credit hold on a chain cascades four levels deep, from the customer through its agreements, scheduled runs, and allocated lots. Money is computed twice under two variants — a provisional payment at lot receiving and a storage-adjusted final settlement at contract close — under a pinned rounding order. All mutations and their cascades are immediately consistent: every effect described for an operation is visible in that operation's response.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts and principles that apply uniformly across the API. Business workflows and the rules specific to each lifecycle appear in §3.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly nine roles, spelled as follows: `PlatformAdmin`, `GrowerRelationsManager`, `Grower`, `StorageOperator`, `QualityAssuranceLead`, `ProductionPlanner`, `AccountManager`, `ChainCustomer`, and `LogisticsCoordinator`. A request missing either header, or presenting an `X-User-Role` value outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Each operation restricts which roles may invoke it; an authenticated caller whose role is not in the operation's role list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). All nine roles may invoke every read (GET) endpoint in the API.

Two roles are entity-backed, meaning their `X-User-ID` is the `id` of a persisted resource and ownership checks compare resource fields against it. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower`; ownership checks on any resource that references a grower compare the resource's foreign-key field to `X-User-ID` — concretely, a grower may deliver a contracted potato lot only against a crop contract whose `grower_id` equals the caller's `X-User-ID`, and any mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `ChainCustomer`, `X-User-ID` is the `id` of the acting `CustomerChain`; the chain customer may author a cut specification only with `customer_id` equal to `X-User-ID`, and may request a revision only on a specification it owns, with violations likewise rejected as `ERR_OWNERSHIP_MISMATCH`.

The remaining seven roles are opaque. For `PlatformAdmin`, `GrowerRelationsManager`, `StorageOperator`, `QualityAssuranceLead`, `ProductionPlanner`, `AccountManager`, and `LogisticsCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`. One ownership-adjacent rule applies by role rather than by identity: creating an import-sourced potato lot (one referencing a shortage event) requires the `GrowerRelationsManager` role, and any other role attempting it is rejected with `ERR_OWNERSHIP_MISMATCH`.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order.

List responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the API — growers, crop contracts, potato lots, storage facilities, processing lines, cut specifications, customer chains, supply agreements, production runs, shipments, and shortage events — carries a standard set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource, including mutations driven by system cascades, derived-field reconciliation, and automatic state transitions — not only client-initiated writes.

Any change to a resource — whether a client-driven state transition, a recalculation of a derived field such as a facility's `current_stock_cwt` or a chain's `fill_rate_pct`, or an automatic sweep transition — refreshes `updated_at` and increments `version`. One entity deviates from this convention: the `ByproductBatch` is an immutable system-created record and carries only `id` and `created_at`; it has neither `updated_at` nor `version`. The atmospheric readings appended to a storage facility's `recent_readings` array are likewise immutable once recorded.

### 2.5. The Logical Clock and the Term-End Sweep

The server maintains a logical clock that governs all time-dependent behavior: delivery-window enforcement on lot intake, storage-decay accrual at settlement, and agreement term expiry. The clock is set exclusively through a platform endpoint whose exact path is `POST /_clock/set_current_utc`. This endpoint is deliberately **not** mounted under the business API's `/potato-ops` prefix — the path is `/_clock/set_current_utc` verbatim. It is restricted to the `PlatformAdmin` role, accepts a single input field `current_utc`, and returns HTTP 200 with an empty data object.

Before any call, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it must never fall back to wall-clock time. Setting the clock performs a term-end sweep in the same operation: every supply agreement in `ACTIVE` status whose `term_end` is at or before the supplied `current_utc` transitions to `COMPLETED`, its reserved weekly cases are released back to the plant pool, and its `version` increments. Clients that need "now" must set it explicitly.

### 2.6. Money, Precision, and the Pinned Rounding Order

All monetary amounts are integers denominated in cents: contract prices in `base_price_per_cwt_cents`, sell prices in `price_per_case_cents`, lot payments in `provisional_payment_cents` and `final_payment_cents`, contract totals in `settlement_amount_cents`, shipment billing in `invoice_cents` and `credit_memo_cents`, and byproduct revenue in `unit_revenue_cents_per_cwt` and `total_revenue_cents`. Every rounding in the system uses the round-half-up method.

Two rounding orders are pinned and must not be reordered. First, per-lot rounding: each potato lot's payment is computed and rounded to whole cents individually, and any contract-level total is the plain sum of those already-rounded per-lot values — a total is never rounded a second time. Second, per-line rounding: a shipment's invoice or credit memo computes each shipment line's cents and rounds that line to whole cents before summing the rounded lines; the raw products are never summed first and rounded once. These orders are observable — for example, two shipment lines of 3 and 2 cases at 305 cents per case produce line amounts of 778 and 519 cents summing to an invoice of 1297 cents, whereas summing before rounding would yield 1296.

Precision varies by quantity and is stated with each rule in §3: contracted volume to 1 decimal place, lot net weight and shrinkage to 2 decimal places, storage loss percentage to 2 decimal places, fill rate to 1 decimal place, and all payment, invoice, credit, and revenue figures to whole cents. Case yields on the production line floor to whole cases at each pass.

### 2.7. The Plant Weekly Case Pool

The plant can ship at most 100,000 finished cases per week across all customers. This capacity is a single shared pool, reserved incrementally by supply agreements: the reserved amount is the sum of `weekly_contracted_cases` over every agreement currently in `ACTIVE` status, and the remaining pool is 100,000 minus that sum. Activating an agreement succeeds only when the remaining pool is at least the agreement's `weekly_contracted_cases`; the boundary is inclusive, so a reservation that draws the pool down to exactly zero is allowed. A request that would oversubscribe the pool is rejected with `ERR_WEEK_CAPACITY_EXCEEDED` (HTTP 422).

Reservations move with the agreement lifecycle. Suspension releases an agreement's weekly cases back into the pool; resumption re-reserves them; completion via the term-end sweep releases them permanently. Re-reservation is atomic across the whole set being resumed: if the pool cannot refit every agreement being restored, the operation that triggered the resumption fails outright with `ERR_WEEK_CAPACITY_EXCEEDED` and nothing changes.

### 2.8. Storage Posture as a Food-Safety Gate

Every storage facility carries a derived `posture` of `NORMAL`, `WATCH`, or `QUARANTINED`, recomputed from the facility's latest atmospheric reading each time a reading is recorded (the derivation thresholds are specified in §3.3). A facility is created in `NORMAL` posture. Posture is not merely informational: it is a food-safety isolation boundary that gates raw-product movement. Receiving a new lot into a `QUARANTINED` facility is rejected with `ERR_FACILITY_QUARANTINED` (HTTP 409), and scheduling a production run that would consume a lot stored in a `QUARANTINED` facility is rejected with the same error. Lots already inside a quarantined facility are not destroyed — they simply cannot move until the posture clears. Posture also modulates storage decay at contract settlement, as described in §3.1.

### 2.9. Optimistic Concurrency Control

Exactly one operation in the API participates in optimistic concurrency control: accepting a pending amendment on a crop contract. A request to accept an amendment must carry the non-optional input field `expected_crop_contract_version`, holding the `version` of the crop contract the client last observed. If that value does not equal the contract's current `version` at the moment of acceptance — because another writer has since advanced the contract, for example by a lot delivery flipping it to `FULFILLED` or a prior acceptance already applying — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from applying terms against a contract state it never observed. No other endpoint in the API takes a version field.

### 2.10. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed priority order and returns the first failure encountered. The order is:

1. **Header presence and role validity** — the `X-User-ID` and `X-User-Role` headers must both be present and the role must be one of the nine declared roles; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to every endpoint.
2. **Role authorization** — the role must appear in the endpoint's authorized role list; otherwise `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Applies to every endpoint.
3. **Entity-backed ownership** — a `Grower` caller may create a lot only against a contract whose `grower_id` equals `X-User-ID`; a `ChainCustomer` caller may create a specification or request its revision only where `customer_id` equals `X-User-ID`; and import-mode lot creation requires the `GrowerRelationsManager` role. Violations are `ERR_OWNERSHIP_MISMATCH` (HTTP 403).
4. **Request shape** — required fields present, enum members valid, numeric bounds respected (weights positive, tare below gross, window start before end, trailer setpoint at or below freezing, exactly one of `contract_id` or `shortage_event_id` on lot creation); otherwise `ERR_INVALID_REQUEST` (HTTP 400). Applies to every endpoint.
5. **Existence** — path identifiers are resolved first, left to right, followed by body foreign-key identifiers in the endpoint's declared input order; each must resolve to an existing entity or the request fails with the matching not-found error (`ERR_GROWER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_SPEC_NOT_FOUND`, `ERR_CHAIN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_SHORTAGE_EVENT_NOT_FOUND`), all HTTP 404.
6. **State preconditions** — the target resource must be in the state its transition requires (contract `DRAFT`, `ACTIVE`, or `AMENDMENT_PENDING` per transition; contract `ACTIVE` for a contracted lot delivery; agreement activatable; specification awaiting validation or revisionable; run stage order; lot `IN_STORAGE`; shipment `IN_TRANSIT`; shortage event `OPEN`). Violations surface as the corresponding state error — `ERR_CONTRACT_NOT_DRAFT`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_CONTRACT_NOT_IN_AMENDMENT`, `ERR_AGREEMENT_NOT_ACTIVABLE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_SPEC_NOT_AWAITING_VALIDATION`, `ERR_SPEC_NOT_REVISIONABLE`, `ERR_SPEC_NOT_VALIDATED`, `ERR_SPEC_NOT_LOCKED`, `ERR_RUN_INVALID_STAGE`, `ERR_LOT_NOT_AVAILABLE`, `ERR_SHIPMENT_NOT_IN_TRANSIT`, `ERR_SHORTAGE_EVENT_NOT_OPEN`, or `ERR_INVALID_STATE` — all HTTP 409.
7. **Quarantine isolation** — lot intake into a `QUARANTINED` facility, or run creation consuming a lot from a `QUARANTINED` facility, is rejected with `ERR_FACILITY_QUARANTINED` (HTTP 409).
8. **Structural constraints** — delivery-window overlap between sibling contracts of the same grower and variety, line schedule conflicts including the changeover buffer, cut-family capability of the line, and stale spec pins at run creation: `ERR_DELIVERY_WINDOW_OVERLAP`, `ERR_LINE_SCHEDULE_CONFLICT`, `ERR_CUT_FAMILY_UNSUPPORTED`, or `ERR_SPEC_REVISION_STALE`, all HTTP 409.
9. **Delivery timing and variety** — a contracted lot must arrive with the logical clock inside the contract's delivery window and must match the contract's variety; otherwise `ERR_OUTSIDE_DELIVERY_WINDOW` or `ERR_VARIETY_MISMATCH`, both HTTP 422.
10. **Capacity, inventory, and quality thresholds** — facility free capacity must absorb the lot's net weight (`ERR_FACILITY_CAPACITY_EXCEEDED`), the plant weekly pool must absorb the agreement (`ERR_WEEK_CAPACITY_EXCEEDED`), shipment cases must not exceed the agreement's released-unshipped inventory (`ERR_UNRELEASED_CASES_EXCEEDED`), a sensory-gated validation needs a panel score of at least 7.0 (`ERR_PANEL_SCORE_BELOW_STANDARD`), and a released run's measured color must sit within half a unit of target (`ERR_COLOR_OUT_OF_TOLERANCE`) — all HTTP 422.
11. **Credit and SLA gates** — agreement activation requires the chain in `GOOD_STANDING` (`ERR_CREDIT_HOLD_ACTIVE`, HTTP 409), and shipment creation requires the agreement not be under SLA review (`ERR_AGREEMENT_UNDER_SLA_REVIEW`, HTTP 409).
12. **Optimistic concurrency** — amendment acceptance requires `expected_crop_contract_version` to match the contract's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412).

Because the API's resources are all top-level (there is no nested URL hierarchy), existence checking reduces to rule 5: path ids left to right, then body foreign keys in the endpoint's declared input order, with the first unresolvable id determining the 404 returned.

## 3. Business Logic & Workflows

This section walks the operational lifecycles of the system in business order: from the grower contract, through receiving and storage, into customer specifications and supply agreements, onto the processing line, out through cold-chain freight, and finally into shortage response. The HTTP contract for every operation named here appears in §4; error conditions named inline refer to the catalogue in §5.

### 3.1. Grower Contracting: Seasons, Amendments, and Settlement

Procurement begins with the grower registry. A `GrowerRelationsManager` registers each grower with a unique `grower_code` (for example, GR-100), the grower's `legal_name`, and a `region` of `COLUMBIA_BASIN`, `SNAKE_RIVER_VALLEY`, `RED_RIVER_VALLEY`, or `MAINE_AROOSTOOK`.

Against a registered grower, the same manager opens a crop contract in `DRAFT` status. The contract names its `grower_id` (immutable after creation), a `variety` of `RUSSET_BURBANK`, `RANGER_RUSSET`, `UMATILLA_RUSSET`, or `CLEARWATER_RUSSET`, the `contracted_acres` (which must be greater than zero), the `expected_yield_cwt_per_acre` (also greater than zero), and the `base_price_per_cwt_cents`, an integer number of cents per hundredweight, greater than zero. The `delivery_window_start` is the inclusive start of the contracted delivery window and `delivery_window_end` its inclusive end, which must fall strictly after the start. From these terms the system derives the read-only `contracted_volume_cwt`: the product of `contracted_acres` and `expected_yield_cwt_per_acre`, rounded half-up to one decimal place. This volume is recomputed whenever an amendment is accepted.

Two contracts of the same grower and the same variety may not hold overlapping delivery windows while either is still live. The check considers every sibling contract of that grower and variety whose status is `DRAFT`, `ACTIVE`, or `AMENDMENT_PENDING` — contracts in the terminal states `FULFILLED` and `SHORTFALL_DECLARED` no longer block. Windows are compared as half-open intervals, start inclusive and end exclusive: an overlap exists when the existing window's start falls before the candidate window's end and the candidate window's start falls before the existing window's end. Adjacency is not overlap — a candidate starting exactly when a sibling ends, or ending exactly when a sibling starts, is allowed, so back-to-back seasons merge cleanly. A conflicting creation, or an amendment acceptance that would create a conflict, is rejected with `ERR_DELIVERY_WINDOW_OVERLAP`. This check runs at contract creation and again when a pending amendment is accepted. The contracts list can be filtered by `grower_id`, `status`, and `variety`.

Activation moves a contract from `DRAFT` to `ACTIVE`, requires the referenced grower to exist (`ERR_GROWER_NOT_FOUND` otherwise), and is rejected with `ERR_CONTRACT_NOT_DRAFT` when the contract is in any other state. Only an `ACTIVE` contract accepts deliveries.

Commercial terms change through a two-step amendment cycle. Proposing an amendment — allowed only while the contract is `ACTIVE`, else `ERR_CONTRACT_NOT_ACTIVE` — carries replacement terms for `contracted_acres`, `expected_yield_cwt_per_acre`, `base_price_per_cwt_cents`, `delivery_window_start`, and `delivery_window_end`; the proposal is stored in the contract's `pending_amendment` object and the contract moves to `AMENDMENT_PENDING`. While no amendment is pending, `pending_amendment` is null. Accepting the amendment returns the contract to `ACTIVE`: the request must arrive while the contract is `AMENDMENT_PENDING` (`ERR_CONTRACT_NOT_IN_AMENDMENT` otherwise), must pass the optimistic-concurrency check on `expected_crop_contract_version` described in §2.9, and must clear the delivery-window overlap check against the amended window. On acceptance the pending terms are applied to the contract, `pending_amendment` returns to null, and `contracted_volume_cwt` is recomputed from the amended acreage and yield. Each of these transitions increments the contract's `version`.

A contract closes in one of two ways, both running the same final settlement. When the crop falls short, a `GrowerRelationsManager` declares the shortfall on an `ACTIVE` contract (`ERR_CONTRACT_NOT_ACTIVE` otherwise), moving it to `SHORTFALL_DECLARED`. Alternatively, delivery itself closes the contract: immediately after a newly received contracted lot is counted, if the contract's `delivered_volume_cwt` has reached at least 98 percent of its `contracted_volume_cwt` — the threshold computed as 0.98 times the contracted volume, rounded half-up to one decimal place — the contract transitions automatically to `FULFILLED`. The read-only `delivered_volume_cwt` is the sum of `net_weight_cwt` over all of the contract's lots with `origin` `CONTRACTED`, regardless of lot status; disposing of a lot does not un-deliver it.

Final settlement writes `settlement_amount_cents` on the contract and `final_payment_cents` on every contracted lot. Both fields are null until settlement; `final_payment_cents` is always null for import lots, and `settlement_amount_cents` is computed exactly once, when the contract enters `FULFILLED` or `SHORTFALL_DECLARED`. The evaluation order is pinned to break the circular dependency between grade and shrinkage. Working through the contract's lots — `origin` `CONTRACTED`, any status other than `DISPOSED` — in ascending order of each lot's `created_at`:

1. **Storage loss first, from raw values.** The lot's days in storage are the whole days elapsed between its `created_at` and the settlement clock — the elapsed seconds divided by 86,400 and rounded down, never less than zero. The raw loss percentage is those days multiplied by a daily loss of 0.02 percentage points, multiplied further by the posture factor of the lot's facility **at settlement time**: 1.0 for `NORMAL`, 1.5 for `WATCH`, and 3.0 for `QUARANTINED`. The raw figure is capped at a maximum loss of 15.0 percent, and the resulting `storage_loss_pct` is rounded half-up to two decimal places.
2. **Shrinkage.** The lot's shrinkage in hundredweight is its `net_weight_cwt` multiplied by `storage_loss_pct` and divided by 100, rounded half-up to two decimal places. The lot's final net is its `net_weight_cwt` minus that shrinkage.
3. **Possible downgrade.** The lot's final grade starts as its receiving `grade`. If the lot's `storage_loss_pct` exceeds 10.0 percent, the grade is downgraded one tier: `A` becomes `B`, `B` becomes `C`, `C` stays `C`, and `REJECT` stays `REJECT`.
4. **Payment.** The lot's `final_payment_cents` is the final net hundredweight multiplied by the contract's `base_price_per_cwt_cents` and by the grade multiplier of the final grade — 1.08 for `A`, 1.03 for `B`, 0.88 for `C`, and 0.00 for `REJECT` — rounded half-up to whole cents.

Lots already `DISPOSED` at settlement receive a `final_payment_cents` of exactly zero. The contract's `settlement_amount_cents` is then the plain sum of the per-lot `final_payment_cents` values, which are already rounded; no second rounding is applied to the sum. This final settlement is the second of two payment variants: the provisional payment computed at receiving (§3.2) uses the receiving-time grade and the full `net_weight_cwt` with no shrinkage and no downgrade, so the two diverge whenever a lot's storage loss is greater than zero.

### 3.2. Receiving Raw Potatoes: Intake Modes and Lot Grading

A potato lot is received in exactly one of two modes, and the request must carry exactly one of `contract_id` or `shortage_event_id` — a request with both or with neither is rejected with `ERR_LOT_SOURCE_MODE_INVALID` (HTTP 400). In **contracted mode**, the lot delivers against a crop contract: the caller must be the `Grower` whose `X-User-ID` equals the contract's `grower_id`, the contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE` otherwise), the logical clock must fall inside the contract's delivery window — from `delivery_window_start` through `delivery_window_end`, inclusive at both ends (`ERR_OUTSIDE_DELIVERY_WINDOW` otherwise) — and the lot's `variety` must equal the contract's variety (`ERR_VARIETY_MISMATCH` otherwise). In **import mode**, used for shortage-response sourcing, the caller must be a `GrowerRelationsManager` and the referenced shortage event must be `OPEN` (`ERR_SHORTAGE_EVENT_NOT_OPEN` otherwise). The system sets the lot's read-only `origin` to `CONTRACTED` or `IMPORT` according to which identifier was supplied.

Both modes share the same physical intake fields: the `facility_id` of the storage cell the lot is received into (immutable after creation), the `variety` (one of the four contract varieties), the `gross_weight_cwt` delivered (greater than zero), the `tare_weight_cwt` (zero or greater, and strictly less than the gross weight), the measured `defect_pct` (a percentage from 0 to 100), the measured `specific_gravity` (for example 1.085), and the fry-color `sugar_end_rating` on a scale of 1.0 to 5.0, where lower is better. From the weights the system derives the read-only `net_weight_cwt`: gross minus tare, rounded half-up to two decimal places.

Grading is computed at receiving and is read-only. A lot whose `defect_pct` is 8.0 or greater is `REJECT` regardless of its other metrics — the defect override is evaluated first. Otherwise each metric earns a tier. The defect tier is `A` when `defect_pct` is below 3.0, `B` when below 5.0, and `C` otherwise. The gravity tier is `A` when `specific_gravity` is at least 1.080, `B` when at least 1.070, `C` when at least 1.060, and `REJECT` below that. The sugar tier is `A` when `sugar_end_rating` is at most 2.0, `B` when at most 3.0, `C` when at most 4.0, and `REJECT` above that. The lot's `grade` is the worst of the three tiers on the ordering where `A` outranks `B`, `B` outranks `C`, and `C` outranks `REJECT`; any `REJECT` tier makes the lot `REJECT`. Inputs are compared exactly as given, with no rounding. A `REJECT` lot is still persisted like any other.

For contracted lots only, receiving also computes the read-only `provisional_payment_cents`: the lot's `net_weight_cwt` multiplied by the contract's `base_price_per_cwt_cents` and by the grade multiplier — 1.08 for `A`, 1.03 for `B`, 0.88 for `C`, 0.00 for `REJECT` — with the single per-lot product rounded half-up to whole cents. Import lots carry a null `provisional_payment_cents`, and every lot's `final_payment_cents` stays null until its contract settles (§3.1).

Receiving mutates the facility and the contract. The destination facility must not be `QUARANTINED` (`ERR_FACILITY_QUARANTINED`), and its free capacity — `capacity_cwt` minus its `current_stock_cwt` — must be at least the lot's `net_weight_cwt`, else `ERR_FACILITY_CAPACITY_EXCEEDED` (HTTP 422). On success the facility's `current_stock_cwt` increases by the lot's net weight, and a contracted delivery grows the contract's `delivered_volume_cwt`, which may push the contract over the automatic 98-percent fulfillment threshold described in §3.1. The lots list can be filtered by `contract_id`, `facility_id`, `shortage_event_id`, and `status`.

### 3.3. The Storage Cell: Atmosphere Readings, Posture, and Disposal

Storage facilities are provisioned by a `PlatformAdmin` with a unique `facility_code` (for example, CELL-1), a `capacity_cwt` greater than zero, and the climate targets `target_temp_f` and `target_co2_pct`. A new facility starts in `NORMAL` posture with a `current_stock_cwt` of zero. That stock figure is a live derived quantity: the sum of `net_weight_cwt` over the facility's lots in `IN_STORAGE` status, so a lot stops contributing the moment it becomes `ALLOCATED` or `DISPOSED`.

A `StorageOperator` keeps each facility honest by recording atmosphere readings, each carrying `recorded_at`, `temperature_f`, `humidity_pct`, `co2_pct`, `sprout_index`, and `disease_incidence_pct`. Readings are appended to the facility's `recent_readings` array, which retains only the ten most recent entries, and a recorded reading can never be modified. Each new reading recomputes the facility's `posture` from the latest reading alone — the one with the greatest `recorded_at`, with ties broken in favor of the reading appended last. The thresholds are inclusive: if the latest reading's `disease_incidence_pct` is at least 6.0 or its `sprout_index` is at least 4.0, the posture becomes `QUARANTINED`; otherwise, if `disease_incidence_pct` is at least 3.0 or `sprout_index` is at least 2.0 — a sprout index of exactly 2.0 already qualifies — the posture becomes `WATCH`; otherwise the facility is `NORMAL`. All six transitions among the three postures occur automatically as readings arrive: `NORMAL` to `WATCH` or `QUARANTINED` when thresholds are crossed, `WATCH` back to `NORMAL` when a reading clears every threshold or onward to `QUARANTINED`, and `QUARANTINED` back to `WATCH` or directly to `NORMAL` as conditions recover. Every posture change increments the facility's `version`. Posture gates lot movement as described in §2.8 and multiplies storage decay at settlement as described in §3.1.

When a stored lot cannot be sold or processed, a `QualityAssuranceLead` disposes of it. Disposal requires the lot to be `IN_STORAGE` (`ERR_LOT_NOT_AVAILABLE` otherwise) and names a `disposition` of `CONDEMNED_WASTE`, `CATTLE_FEED`, or `STARCH_RECOVERY` (any other value is `ERR_INVALID_REQUEST`). The lot moves to `DISPOSED`, its `disposition` field — null until this moment — records the chosen routing, its facility's `current_stock_cwt` falls by the lot's `net_weight_cwt`, and the system books a `ByproductBatch` with `stream` `WHOLE_LOT`, `routing` copied from the disposition, `weight_cwt` equal to the lot's `net_weight_cwt`, and `source_lot_id` pointing at the lot (with `source_run_id` null).

Byproduct batches are the system's record of diverted value. The batch's `unit_revenue_cents_per_cwt` follows a fixed tariff by routing: 900 cents per hundredweight for `CATTLE_FEED`, 1,400 for `STARCH_RECOVERY`, and 0 for `CONDEMNED_WASTE`. Its read-only `total_revenue_cents` is the `weight_cwt` multiplied by that unit tariff, rounded half-up to whole cents. Batches are created only by the system — never by clients — and are immutable; as noted in §2.4 a batch carries only `id` and `created_at`. The batches list can be filtered by `source_run_id`, `source_lot_id`, and `routing`.

### 3.4. Customer Cut Specifications: Validation, Locking, and Revision

A chain customer describes its product by authoring a cut specification. The caller must be a `ChainCustomer` whose `X-User-ID` equals the payload's `customer_id` (`ERR_OWNERSHIP_MISMATCH` otherwise). The specification carries a customer-unique `spec_code` (for example, SP-3814), a `cut_family` of `STRAIGHT`, `CRINKLE`, `WEDGE`, or `SHOESTRING`, a `cut_size_mm` greater than zero, a `coating_type` of `NONE`, `CLEAR`, `SEASONED`, or `BATTER`, a `target_color_units` on the 0-to-4 post-cook fry-color scale, a `max_cook_time_sec` greater than zero, and an optional `sensory_panel_required` flag that defaults to true. A new specification starts in `SUBMITTED` status, with `ever_locked` false and `panel_score` null.

Validation is performed by a `QualityAssuranceLead`, who records the sensory panel outcome as a `panel_score` input. The specification must be `SUBMITTED` or `REVISION_REQUESTED` (`ERR_SPEC_NOT_AWAITING_VALIDATION` otherwise). When `sensory_panel_required` is true, the score must be at least 7.0 or the validation is rejected with `ERR_PANEL_SCORE_BELOW_STANDARD` (HTTP 422); when the flag is false, the `panel_score` input is still required but any score of 0 or better passes. The destination state depends on history: from `SUBMITTED` the spec moves to `VALIDATED`; from `REVISION_REQUESTED` it moves to `VALIDATED` if it has never been locked, but directly back to `LOCKED` if `ever_locked` is true. In every branch the recorded score replaces `panel_score` as the most recent panel result. Agreements already pinned to the spec keep their `spec_stale` flag set until they re-acknowledge, as described in §3.5.

Locking happens implicitly: the first time a supply agreement referencing a `VALIDATED` specification is activated, the specification transitions to `LOCKED`, sets `ever_locked` to true, and increments its `version`. The `ever_locked` flag is never cleared, which is what steers later re-validations of a revised spec back to `LOCKED`.

Revision is customer-initiated: a `ChainCustomer` may request a revision on a specification in `VALIDATED` or `LOCKED` (`ERR_SPEC_NOT_REVISIONABLE` otherwise), and only on its own specifications — `X-User-ID` must equal the specification's `customer_id` (`ERR_OWNERSHIP_MISMATCH` otherwise). The spec moves to `REVISION_REQUESTED`. When the revised spec was `LOCKED`, the revision also flags downstream staleness: every `ACTIVE` supply agreement whose `pinned_spec_version` equals the specification's pre-revision `version` has its `spec_stale` set to true. A revision from `VALIDATED` has no such cascade, because no agreement could yet have pinned the spec. The specifications list can be filtered by `customer_id` and `status`.

### 3.5. Supply Agreements, Weekly Capacity, and Credit Posture

An `AccountManager` registers each chain customer with a unique `chain_code` (for example, CH-BURGER), a `legal_name`, and a `priority_tier` of `TIER_1_STRATEGIC`, `TIER_2_PREFERRED`, or `TIER_3_STANDARD` — the tier that later drives shortage waterfall order (§3.8). A chain begins with `credit_status` `GOOD_STANDING` and a `fill_rate_pct` of null, the rate staying null until the chain's first shipment reaches a terminal state, at or after which it is maintained as described in §3.7.

A supply agreement is created in `DRAFT` against a `customer_id` and a `spec_id` — the cut specification this agreement buys against — with `weekly_contracted_cases` of at least 1, a `price_per_case_cents` greater than zero, and a term from `term_start` (inclusive) to `term_end` (inclusive, and strictly after the start). While `DRAFT`, the agreement's `pinned_spec_version` is null, and `spec_stale` and `under_sla_review` are both false.

Activation by an `AccountManager` is where the agreement becomes real. The agreement must be `DRAFT` — or `ACTIVE` with `spec_stale` true, the re-acknowledgment branch below — else `ERR_AGREEMENT_NOT_ACTIVABLE`. The chain must be in `GOOD_STANDING` (`ERR_CREDIT_HOLD_ACTIVE`), the specification must be `VALIDATED` or `LOCKED` (`ERR_SPEC_NOT_VALIDATED`), and the plant weekly pool must absorb the agreement (`ERR_WEEK_CAPACITY_EXCEEDED`, per §2.7). On a first activation the agreement becomes `ACTIVE`; `pinned_spec_version` captures the specification's current `version`; `spec_stale` is cleared; `current_week_allocation_cases` is initialized to `weekly_contracted_cases`; and the weekly cases are reserved from the plant pool. If the specification was still `VALIDATED`, this same activation locks it, as described in §3.4.

The second branch of activation is the re-acknowledgment of a stale spec pin. When an `ACTIVE` agreement carries `spec_stale` true — because its pinned specification passed through a revision — re-activating it re-pins `pinned_spec_version` to the specification's current `version` and clears `spec_stale`. This branch requires the specification to be `LOCKED` again (`ERR_SPEC_NOT_LOCKED` otherwise); an `ACTIVE` agreement without a stale pin is not activatable at all (`ERR_AGREEMENT_NOT_ACTIVABLE`).

Credit posture is controlled on the chain. Setting `credit_status` to a value equal to the current one is rejected with `ERR_INVALID_STATE`. Placing a chain `ON_HOLD` triggers the deepest cascade in the system, applied immediately within the same response: first, every `ACTIVE` supply agreement of the chain moves to `SUSPENDED`, releasing its reserved weekly cases back to the plant pool; second, for each suspended agreement, every production run still in `SCHEDULED` moves to `CANCELLED`; third, for each cancelled run, every input lot that was `ALLOCATED` to it returns to `IN_STORAGE`, and each lot's facility regains the lot's `net_weight_cwt` in its `current_stock_cwt`. Returning the chain to `GOOD_STANDING` reverses the first link only: every `SUSPENDED` agreement moves back to `ACTIVE` and re-reserves its `weekly_contracted_cases` from the pool. If the pool cannot refit all of them, the entire set-credit-status call fails with `ERR_WEEK_CAPACITY_EXCEEDED` and nothing changes. Cancelled runs and the lots they deallocated are not resurrected. Finally, the term-end sweep of §2.5 moves an `ACTIVE` agreement to `COMPLETED` once the logical clock reaches its `term_end`, releasing its weekly cases permanently.

Three read-only counters track each agreement's throughput. `lifetime_released_cases` is the sum of `actual_cases` over the agreement's `RELEASED` production runs. `lifetime_shipped_cases` is the sum of `cases_shipped` over the agreement's shipments in `IN_TRANSIT` or `DELIVERED` status — cases on a shipment rejected on arrival are never returned to inventory. `released_unshipped_cases` is the difference between the two, and it caps what a shipment may draw (§3.7). Separately, `current_week_allocation_cases` records how many cases the agreement may ship in the current week: initialized to `weekly_contracted_cases` at activation and overwritten by shortage allocation (§3.8). The agreements list can be filtered by `customer_id`, `spec_id`, and `status`.

### 3.6. Running the Processing Line: Scheduling, Stages, and the QA Gate

Processing lines are provisioned by a `PlatformAdmin` with a unique `line_code` (for example, LINE-1), a non-empty `supported_cut_families` array drawn from the four cut families, and a `rated_throughput_cases_per_hour` greater than zero.

A `ProductionPlanner` schedules a production run by naming a `line_id`, a `spec_id`, an `agreement_id`, a non-empty `input_lot_ids` array of whole lots to consume, and a window from `scheduled_start` (inclusive) to `scheduled_end` (exclusive, and strictly after the start). Creation enforces a chain of gates. The specification must be `LOCKED` (`ERR_SPEC_NOT_LOCKED`), and the specification's `cut_family` must appear among the line's `supported_cut_families` (`ERR_CUT_FAMILY_UNSUPPORTED`). The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), must not carry a stale spec pin (`ERR_SPEC_REVISION_STALE`), and must belong to a chain in good standing — a chain placed on credit hold has every agreement suspended, so the credit gate surfaces here as the agreement no longer being `ACTIVE`. Every input lot must be `IN_STORAGE` (`ERR_LOT_NOT_AVAILABLE`) and held in a facility that is not `QUARANTINED` (`ERR_FACILITY_QUARANTINED`).

The run must also fit the line's schedule. The candidate window is compared against every existing run on the same line whose status is still live — `SCHEDULED`, `CUTTING`, `BLANCHING`, `COATING`, `FREEZING`, `QA_HOLD`, or `REWORK`; terminal runs in `RELEASED`, `REJECTED`, or `CANCELLED` do not block. If the windows strictly overlap — the existing run starts before the candidate ends and the candidate starts before the existing run ends — creation is always rejected with `ERR_LINE_SCHEDULE_CONFLICT`. When the windows are disjoint or merely touching, a cut-family change demands a changeover buffer: if the candidate's `cut_family` differs from the existing run's, the gap between the intervals (the candidate's start minus the existing run's end when the candidate follows, or the existing run's start minus the candidate's end when it precedes) must be at least 60 minutes; any smaller gap, including exact adjacency, is rejected with `ERR_LINE_SCHEDULE_CONFLICT`. Runs of the same cut family may follow each other with any gap of zero or more, exact adjacency included.

On creation the run's `cut_family` is copied from the specification, its read-only `total_input_cwt` is computed as the sum of `net_weight_cwt` over the input lots, and every input lot moves from `IN_STORAGE` to `ALLOCATED`, with each lot's facility losing the lot's net weight from `current_stock_cwt`. The run starts in `SCHEDULED`, with `actual_cases` null and `rework_count` zero.

Execution advances one stage at a time, driven by a `ProductionPlanner`: `SCHEDULED` to `CUTTING` to `BLANCHING` to `COATING` to `FREEZING` to `QA_HOLD`, with the rework path re-entering from `REWORK` to `COATING`. Advancing from any other stage — including the terminal `RELEASED`, `REJECTED`, or `CANCELLED` — is rejected with `ERR_RUN_INVALID_STAGE`. Every entry into `QA_HOLD`, whether the first pass or a re-entry after rework, computes the run's `actual_cases`. On the first pass (`rework_count` zero), the figure is the run's `total_input_cwt` multiplied by the yield for its cut family — 0.62 cases per hundredweight for `STRAIGHT`, 0.58 for `CRINKLE`, 0.66 for `WEDGE`, and 0.55 for `SHOESTRING` — rounded down to whole cases. On a re-entry after rework, the figure is the previous `actual_cases` multiplied by 0.96 — a 4 percent rework loss — again rounded down to whole cases.

Three outcomes leave `QA_HOLD`, all gated to that stage (`ERR_RUN_INVALID_STAGE` otherwise). A `QualityAssuranceLead` may send the run back for rework, moving it to `REWORK` and incrementing `rework_count` by one. Releasing the run requires a `measured_color_units` reading whose absolute difference from the specification's `target_color_units` is at most 0.5 (`ERR_COLOR_OUT_OF_TOLERANCE`, HTTP 422, otherwise); a release moves the run to `RELEASED`, transitions every input lot from `ALLOCATED` to `CONSUMED`, and adds the run's `actual_cases` to the agreement's `lifetime_released_cases`. Rejecting the run requires a `disposition` of `CONDEMNED_WASTE` or `CATTLE_FEED` (any other value, including `STARCH_RECOVERY`, is `ERR_INVALID_REQUEST`); the run moves to `REJECTED`, its input lots are likewise consumed, and the system books a `ByproductBatch` with `stream` `REJECTED_PRODUCT`, `routing` copied from the disposition, `weight_cwt` equal to the run's `total_input_cwt`, and `source_run_id` pointing at the run (with `source_lot_id` null).

Cancellation is never client-initiated. A run leaves `SCHEDULED` for `CANCELLED` only through the credit-hold cascade of §3.5, which returns its input lots to `IN_STORAGE` and restores their weight to their facilities' stock. The runs list can be filtered by `line_id`, `spec_id`, `agreement_id`, and `status`.

### 3.7. Cold-Chain Shipments: Delivery, Invoicing, and the Fill-Rate Loop

A `LogisticsCoordinator` consolidates released product into a shipment against a single agreement. The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`) and must not be under SLA review (`ERR_AGREEMENT_UNDER_SLA_REVIEW`, HTTP 409). The shipment names a `carrier_name`, a `trailer_setpoint_f` that must be at or below 0.0 degrees Fahrenheit — the frozen cold-chain requirement, with any warmer setpoint rejected as `ERR_INVALID_REQUEST` — and a `route_type` of `DIRECT_CHAIN` or `DISTRIBUTOR`. Its `lines` are a non-empty array of entries, each pairing a `run_id` with a number of `cases`; every referenced run must exist (`ERR_RUN_NOT_FOUND`), must be `RELEASED`, and must belong to this agreement, with a run of another agreement or a run not yet released rejected as `ERR_INVALID_REQUEST`. The total cases across the lines must not exceed the agreement's `released_unshipped_cases` (`ERR_UNRELEASED_CASES_EXCEEDED`). The read-only `cases_shipped` is the sum of the lines' cases. A new shipment starts `IN_TRANSIT`; `max_transit_temp_f` and `minutes_above_setpoint` stay null until delivery, `invoice_cents` stays null while the shipment is in transit and forever if it is rejected on arrival, and `credit_memo_cents` stays null on any shipment that is not rejected.

Recording a delivery — allowed only while `IN_TRANSIT` (`ERR_SHIPMENT_NOT_IN_TRANSIT`) — captures the cold-chain record: the caller supplies `max_transit_temp_f` and `minutes_above_setpoint`, and the `excursion_flag` is set when the trailer spent strictly more than 30 minutes above its setpoint. The same operation computes the `invoice_cents`. Under the pinned per-line rounding of §2.6, each line bills its cases at the agreement's `price_per_case_cents`, discounted by a factor of 0.90 when the excursion flag is set, with each line rounded half-up to whole cents before the lines are summed. Delivery then recomputes the chain's `fill_rate_pct`, and if the new rate is at least 85.0 the system clears `under_sla_review` on all of the chain's agreements.

A customer refusal instead moves the shipment to `REJECTED_ON_ARRIVAL` — again only from `IN_TRANSIT`. This computes a `credit_memo_cents`: each line credits its cases at the agreement's `price_per_case_cents` multiplied by 0.85, rounded half-up to whole cents per line and summed. Rejected cases are not returned to inventory — `released_unshipped_cases` does not grow back. The rejection also recomputes the chain's `fill_rate_pct`, and if the new rate is below 85.0 the system sets `under_sla_review` to true on every `ACTIVE` agreement of the chain, which in turn blocks new shipments against those agreements until a later delivery lifts the rate back to the floor.

The fill rate itself is defined over the chain's terminal shipments only: the delivered figure is the sum of `cases_shipped` over the chain's `DELIVERED` shipments, the rejected figure the same sum over `REJECTED_ON_ARRIVAL` shipments, and `fill_rate_pct` is one hundred times delivered divided by the sum of delivered and rejected, rounded half-up to one decimal place. `IN_TRANSIT` shipments are excluded, and the rate is null whenever the denominator is zero — that is, until the chain's first terminal shipment. The floor is 85.0: below it, every `ACTIVE` agreement of the chain goes under SLA review; at or above it after a delivery, the review flag clears across the chain. The shipments list can be filtered by `agreement_id` and `status`.

### 3.8. Shortfall Response: Shortage Events, Allocation, and Import Sourcing

When the crop cannot cover commitments, a `GrowerRelationsManager` declares a shortage event with a `scope_variety` (one of the four contract varieties), a `declared_deficit_cwt` greater than zero estimating the raw-potato shortfall, an `available_week_cases` between 1 and 100,000 describing the finished-case pool available for allocation that week, and a `response_mode` of `PRO_RATA` or `PRIORITY_WATERFALL` selecting the allocation variant. The event opens in `OPEN` status with `allocation_results` null. While an event is `OPEN`, import lots may be received against it as described in §3.2.

Executing the allocation — an action reserved to the `GrowerRelationsManager` and rejected with `ERR_SHORTAGE_EVENT_NOT_OPEN` once the event has closed — distributes the available pool across every agreement in `ACTIVE` status at execution time; `SUSPENDED` and `COMPLETED` agreements do not participate. Call the pool D.

Under `PRO_RATA`, the system sums the participants' `weekly_contracted_cases` into a total weekly figure and gives each participant the smaller of its own `weekly_contracted_cases` and D multiplied by its share of that total, rounded down to whole cases — the cap keeps a thin participant set from being allocated more than its contract. Any leftover, the pool minus the sum of allocations, stays unallocated. Tier is ignored in this variant.

Under `PRIORITY_WATERFALL`, participants are ordered by their customer's `priority_tier`, with `TIER_1_STRATEGIC` first, then `TIER_2_PREFERRED`, then `TIER_3_STANDARD`, and ties broken by the agreement's `created_at` in ascending order. Each participant in turn receives the smaller of its `weekly_contracted_cases` and the pool remaining at its turn; allocation stops when the remaining pool reaches zero or participants are exhausted. Higher tiers are thus filled to contract before lower tiers receive anything, so for the same participants and pool the two variants produce different allocations.

Both variants overwrite each participant's `current_week_allocation_cases` and record the event's `allocation_results` as a list of per-agreement entries, each naming an `agreement_id` and its `allocated_cases`, written in the same per-participant order in which they were computed. The event then moves to `EXECUTED` with its `version` incremented. If no agreement is `ACTIVE` at execution time, the participant set is empty: `allocation_results` is recorded as an empty list, no agreement is touched, and the event still transitions to `EXECUTED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, readings, delivery recording, allocation execution, and the logical-clock set — return `200 OK`. The table below is a summary only: request fields, response content, and side effects are defined by the narratives in §2 and §3. Note that the logical-clock endpoint is a platform operation living outside the `/potato-ops` prefix; every other path below is shown in full.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; sweeps agreements past `term_end` to `COMPLETED` | PlatformAdmin |
| POST | `/potato-ops/growers` | Register a grower | GrowerRelationsManager |
| GET | `/potato-ops/growers/{id}` | Get a grower by id | Any |
| POST | `/potato-ops/crop-contracts` | Create a crop contract in `DRAFT`, checking sibling delivery-window overlap | GrowerRelationsManager |
| GET | `/potato-ops/crop-contracts` | List crop contracts with optional filters | Any |
| GET | `/potato-ops/crop-contracts/{id}` | Get a crop contract by id | Any |
| POST | `/potato-ops/crop-contracts/{id}/activate` | Activate a `DRAFT` contract | GrowerRelationsManager |
| POST | `/potato-ops/crop-contracts/{id}/propose-amendment` | Propose replacement commercial terms, moving the contract to `AMENDMENT_PENDING` | GrowerRelationsManager |
| POST | `/potato-ops/crop-contracts/{id}/accept-amendment` | Accept the pending amendment (OCC-guarded) and return the contract to `ACTIVE` | GrowerRelationsManager |
| POST | `/potato-ops/crop-contracts/{id}/declare-shortfall` | Declare a crop shortfall on an `ACTIVE` contract and settle it | GrowerRelationsManager |
| POST | `/potato-ops/potato-lots` | Receive a potato lot in contracted or import mode | Grower, GrowerRelationsManager |
| GET | `/potato-ops/potato-lots` | List potato lots with optional filters | Any |
| GET | `/potato-ops/potato-lots/{id}` | Get a potato lot by id | Any |
| POST | `/potato-ops/potato-lots/{id}/dispose` | Dispose of an `IN_STORAGE` lot, creating a byproduct batch | QualityAssuranceLead |
| POST | `/potato-ops/storage-facilities` | Create a storage facility (posture starts `NORMAL`) | PlatformAdmin |
| GET | `/potato-ops/storage-facilities/{id}` | Get a storage facility with posture, stock, and recent readings | Any |
| POST | `/potato-ops/storage-facilities/{id}/readings` | Record an atmospheric reading and recompute posture | StorageOperator |
| POST | `/potato-ops/processing-lines` | Create a processing line | PlatformAdmin |
| POST | `/potato-ops/cut-specifications` | Create a customer cut specification in `SUBMITTED` | ChainCustomer |
| GET | `/potato-ops/cut-specifications` | List cut specifications with optional filters | Any |
| GET | `/potato-ops/cut-specifications/{id}` | Get a cut specification by id | Any |
| POST | `/potato-ops/cut-specifications/{id}/validate` | Record the sensory panel outcome, validating or re-locking the spec | QualityAssuranceLead |
| POST | `/potato-ops/cut-specifications/{id}/request-revision` | Request a spec revision; from `LOCKED` also flags pinned agreements stale | ChainCustomer |
| POST | `/potato-ops/customer-chains` | Register a chain customer | AccountManager |
| GET | `/potato-ops/customer-chains/{id}` | Get a chain customer | Any |
| POST | `/potato-ops/customer-chains/{id}/set-credit-status` | Set the chain's credit status; `ON_HOLD` cascades to agreements, runs, and lots | AccountManager |
| POST | `/potato-ops/supply-agreements` | Create a supply agreement in `DRAFT` | AccountManager |
| GET | `/potato-ops/supply-agreements` | List supply agreements with optional filters | Any |
| GET | `/potato-ops/supply-agreements/{id}` | Get a supply agreement by id | Any |
| POST | `/potato-ops/supply-agreements/{id}/activate` | Activate a `DRAFT` agreement, or re-acknowledge a stale spec pin on an `ACTIVE` one | AccountManager |
| POST | `/potato-ops/production-runs` | Schedule a production run consuming whole lots | ProductionPlanner |
| GET | `/potato-ops/production-runs` | List production runs with optional filters | Any |
| GET | `/potato-ops/production-runs/{id}` | Get a production run by id | Any |
| POST | `/potato-ops/production-runs/{id}/advance` | Advance the run one pipeline stage | ProductionPlanner |
| POST | `/potato-ops/production-runs/{id}/qa-release` | Release a `QA_HOLD` run after cook-color validation | QualityAssuranceLead |
| POST | `/potato-ops/production-runs/{id}/rework` | Send a `QA_HOLD` run back through coating | QualityAssuranceLead |
| POST | `/potato-ops/production-runs/{id}/reject` | Reject a `QA_HOLD` run, diverting output to a byproduct batch | QualityAssuranceLead |
| GET | `/potato-ops/byproduct-batches` | List byproduct batches with optional filters | Any |
| GET | `/potato-ops/byproduct-batches/{id}` | Get a byproduct batch by id | Any |
| POST | `/potato-ops/shipments` | Create a shipment (starts `IN_TRANSIT`) consolidating released cases by run line | LogisticsCoordinator |
| GET | `/potato-ops/shipments` | List shipments with optional filters | Any |
| GET | `/potato-ops/shipments/{id}` | Get a shipment by id | Any |
| POST | `/potato-ops/shipments/{id}/deliver` | Record delivery with cold-chain transit data; computes excursion flag, invoice, and fill-rate updates | LogisticsCoordinator |
| POST | `/potato-ops/shipments/{id}/reject-on-arrival` | Refuse the shipment; computes the credit memo and the fill-rate cascade | LogisticsCoordinator |
| POST | `/potato-ops/shortage-events` | Declare a crop shortfall event with its available case pool and allocation mode | GrowerRelationsManager |
| POST | `/potato-ops/shortage-events/{id}/execute-allocation` | Run the shortage allocation over all `ACTIVE` agreements and write per-agreement weekly allocations | GrowerRelationsManager |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can return. Trigger conditions for each error are specified where the guarded behavior lives, in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_LOT_SOURCE_MODE_INVALID` | 400 Bad Request |
| `ERR_GROWER_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_SPEC_NOT_FOUND` | 404 Not Found |
| `ERR_CHAIN_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SHORTAGE_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_DRAFT` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_NOT_IN_AMENDMENT` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVABLE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SPEC_NOT_AWAITING_VALIDATION` | 409 Conflict |
| `ERR_SPEC_NOT_REVISIONABLE` | 409 Conflict |
| `ERR_SPEC_NOT_VALIDATED` | 409 Conflict |
| `ERR_SPEC_NOT_LOCKED` | 409 Conflict |
| `ERR_RUN_INVALID_STAGE` | 409 Conflict |
| `ERR_LOT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_SHIPMENT_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_SHORTAGE_EVENT_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_FACILITY_QUARANTINED` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_LINE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_CUT_FAMILY_UNSUPPORTED` | 409 Conflict |
| `ERR_SPEC_REVISION_STALE` | 409 Conflict |
| `ERR_OUTSIDE_DELIVERY_WINDOW` | 422 Unprocessable Entity |
| `ERR_VARIETY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FACILITY_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WEEK_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_UNRELEASED_CASES_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PANEL_SCORE_BELOW_STANDARD` | 422 Unprocessable Entity |
| `ERR_COLOR_OUT_OF_TOLERANCE` | 422 Unprocessable Entity |
| `ERR_CREDIT_HOLD_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_UNDER_SLA_REVIEW` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
