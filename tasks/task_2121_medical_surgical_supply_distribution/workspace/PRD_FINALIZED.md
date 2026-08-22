# Med-Surg Supply Distribution API — Product Requirements Document

## 1. Introduction

Acute-care distribution is the business of moving a manufacturer's product through a contracted price, into a facility's own item catalogue, out of a picked lot, onto a refrigerated van, and finally onto a shelf in an operating-room core — and then billing the manufacturer for the discount the hospital was promised. Every one of those steps is governed by a different party: a contracting desk negotiates the price, a clinician decides whether the item may be stocked at all, a materials manager sets the par level and raises the order, a distribution-centre operator picks the lot and drives the route, and a manufacturer representative accepts or disputes the resulting chargeback. This document specifies the API that ties those parties together for a group-purchasing-organisation (GPO) distributor operating in the McKesson/Cardinal mould.

Three properties make this domain unusually unforgiving. First, **price is not a single number**: the price pinned onto an order line when a materials manager writes it and the price settled against that line when the truck is unloaded are computed by the same formula at two different instants, and a contract that was superseded in between makes them legitimately disagree. Second, **safety cascades outward**: quarantining a single recalled lot has to unwind allocations, re-total orders, release credit commitments, strip stops off a route, and cancel the route itself when nothing is left on it. Third, **two people are required where one person could hide a mistake**: the operator who flags a cold-chain temperature excursion may not be the one who clears it, and the contract administrator who raises a chargeback claim may not be the one who reconciles it.

The API is deliberately transactional and immediately consistent: there is no background settlement worker and no eventual convergence. Every side effect described in this document happens inside the request that triggers it, and every computed field a client can read is correct the moment the response is returned. Time itself is a server-controlled resource — all contract effectivity, lot expiry and delivery timestamps read from a logical clock the contracting desk can move — so that the temporal behaviour of contract supersession and lot expiry is exercisable deterministically rather than by waiting.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to this API — reads included — must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role it acts in. If either header is absent, or if `X-User-Role` carries a string outside the five roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other aspect of the request is inspected. If both headers are well formed but the named role is not among the roles authorised for the endpoint (see the catalogue in §4), the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The five roles are `ContractAdmin`, `MaterialsManager`, `Clinician`, `DistributionOperator` and `ManufacturerRep`, spelled exactly so.

- A `ContractAdmin` is the distributor's contracting and settlement desk. It owns the item master, GPO contract headers and their price lines, contract activation, supply-room registration, recall issuance, chargeback claim creation and settlement, and the logical clock.
- A `MaterialsManager` is a supply-room materials manager. It owns the room's formulary mappings, par levels, cycle counts, replenishment orders and substitution requests.
- A `Clinician` decides formulary standing and approves, rejects or interrogates backorder substitutions.
- A `DistributionOperator` runs the distribution centre: lot receipt and disposition, order picking and delivery, recall cascade execution, and delivery routing.
- A `ManufacturerRep` acts for the manufacturer and either accepts or disputes chargeback claims raised against its contracts.

When `X-User-Role` is `MaterialsManager`, `X-User-ID` is the `id` of the acting `SupplyRoom`; ownership checks on any resource that references a `SupplyRoom` compare the resource's supply-room reference to `X-User-ID`. Concretely, a materials manager may only act on the supply room named in the path, on a `ReplenishmentOrder` whose `supply_room_id` equals its `X-User-ID`, on a `FormularyItem` whose `supply_room_id` equals its `X-User-ID`, or on an order line or substitution request whose owning order belongs to that room. A mismatch is rejected with `ERR_SUPPLY_ROOM_SCOPE_VIOLATION` (HTTP 403). This scope check guards exactly eight operations: creating a formulary mapping under a supply room (`POST /supply-rooms/{supply_room_id}/formulary-items`), posting a cycle-count adjustment (`POST /formulary-items/{formulary_item_id}/adjust-on-hand`), reading a replenishment suggestion (`GET /formulary-items/{formulary_item_id}/replenishment-suggestion`), opening an order (`POST /orders`), writing an order line (`POST /orders/{order_id}/lines`), submitting an order (`POST /orders/{order_id}/submit`), opening a substitution request against an order line (`POST /order-lines/{order_line_id}/substitution-requests`), and responding to a substitution request (`POST /substitution-requests/{substitution_request_id}/respond`). The replenishment suggestion is also readable by a `ContractAdmin`, for whom no scope check applies.

When `X-User-Role` is `ContractAdmin`, `Clinician`, `DistributionOperator` or `ManufacturerRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands attribution — as `submitted_by_user_id` and `reconciled_by_user_id` on a `ChargebackClaim` for a `ContractAdmin`, as `decided_by_user_id` on a `FormularyItem` and `clinician_user_id` on a `SubstitutionRequest` for a `Clinician`, as `excursion_flagged_by_user_id` on a `Lot` and `requested_by_user_id` on a `SubstitutionRequest` for the respective operator role — but it never compares that identifier to any entity's `id`. (`requested_by_user_id` is written by a `MaterialsManager`, whose identifier is a supply-room `id`; it is recorded as attribution all the same.)

Every read endpoint in this API is open to all five roles. Write endpoints are narrow, and the authoritative per-endpoint role list is the table in §4.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1 and a maximum of 100; `offset` defaults to 0 and has a minimum of 0. A `limit` below 1 or above 100, or an `offset` below 0, is a schema violation and is rejected with `ERR_VALIDATION` (HTTP 400) — the values are not silently clamped.

Results are ordered by `created_at` ascending, oldest first, on every list endpoint without exception. Filters offered by a list endpoint narrow the result set before pagination is applied.

For list responses the `meta` object carries `limit` and `offset` as they were resolved for the request, `total_count` as the number of rows matching the filters before `limit` and `offset` were applied, and `has_more`, which is true exactly when rows remain beyond the current page.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every resource in this system — supply rooms, item-master records, GPO contracts, contract lines, formulary mappings, lots, replenishment orders, order lines, substitution requests, recall notices, delivery routes and chargeback claims alike — carries the same four common properties. `id` is a server-minted UUID string with no type prefix, and it is never supplied by a client. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. `version` is an integer that begins at 1 when the resource is created and increments by exactly one on every mutation of that resource, including mutations that arrive as a side effect of an operation aimed at some other resource. Whenever `version` increments, `updated_at` is refreshed to the same instant.

Time in this API is not wall-clock time. The server maintains a **logical clock** that starts at exactly `2026-08-01T00:00:00Z` when the server boots and only ever moves when a `ContractAdmin` sets it, by supplying a `to_iso8601` instant to the clock-setting capability; the response reports the resulting `current_utc`. The clock never falls back to wall-clock time, and setting it mutates no entity — it only changes the instant against which subsequent requests are evaluated. Contract effectivity windows, lot expiry, `activated_at`, `submitted_at`, `delivered_at`, `dispatched_at`, `cascaded_at`, and the `created_at` / `updated_at` stamps written by mutating requests all read from this clock.

### 2.5. Path Resolution and Referential Integrity

Nested paths are resolved strictly left to right, and the first unresolvable segment determines the error. Each path variable has its own dedicated 404: `supply_room_id` yields `ERR_SUPPLY_ROOM_NOT_FOUND`, `item_id` yields `ERR_ITEM_NOT_FOUND`, `contract_id` yields `ERR_CONTRACT_NOT_FOUND`, `contract_line_id` yields `ERR_CONTRACT_LINE_NOT_FOUND`, `formulary_item_id` yields `ERR_FORMULARY_ITEM_NOT_FOUND`, `lot_id` yields `ERR_LOT_NOT_FOUND`, `order_id` yields `ERR_ORDER_NOT_FOUND`, `order_line_id` yields `ERR_ORDER_LINE_NOT_FOUND`, `substitution_request_id` yields `ERR_SUBSTITUTION_REQUEST_NOT_FOUND`, `recall_notice_id` yields `ERR_RECALL_NOTICE_NOT_FOUND`, `route_id` yields `ERR_ROUTE_NOT_FOUND` and `chargeback_claim_id` yields `ERR_CHARGEBACK_CLAIM_NOT_FOUND`. All of them are HTTP 404.

References supplied inside a request body are held to the same standard, one step later in the order of checks. Any of `item_id`, `lot_id`, `lum_parent_item_id`, `supersedes_contract_id`, `supply_room_id`, `order_id`, `contract_id` or `proposed_item_id` that does not resolve to an existing row is a 404, reported under the not-found code of the entity it should have named — `ERR_ITEM_NOT_FOUND` for `item_id`, `lum_parent_item_id` and `proposed_item_id`; `ERR_LOT_NOT_FOUND` for `lot_id`; `ERR_CONTRACT_NOT_FOUND` for `contract_id` and `supersedes_contract_id`; `ERR_SUPPLY_ROOM_NOT_FOUND` for `supply_room_id`; and `ERR_ORDER_NOT_FOUND` for `order_id`. Body-reference resolution is enforced on exactly these eleven write operations: `POST /items`, `POST /contracts`, `POST /contracts/{contract_id}/lines`, `POST /supply-rooms/{supply_room_id}/formulary-items`, `POST /lots`, `POST /orders`, `POST /orders/{order_id}/lines`, `POST /order-lines/{order_line_id}/substitution-requests`, `POST /recall-notices`, `POST /delivery-routes/{route_id}/stops` and `POST /chargeback-claims`.

### 2.6. Cents, Eaches and Rounding Discipline

All monetary quantities in this API are integers denominated in cents; there are no floating-point currency fields and no fractional cents anywhere in storage or in responses. Wherever a rate multiplication produces a fraction, the result is rounded **half up** to a whole cent — a value of exactly one half cent rounds away from zero, upward. The one non-integer field in the system is `admin_fee_pct` on a chargeback claim, which stores the selected administrative-fee rate as a decimal fraction (0.020, 0.015 or 0.010) rather than as a percentage figure.

Rounding placement matters as much as rounding mode, and the two places it matters most are stated where the formulas live: the distribution fee is rounded once per order line and only then summed (§3.4), and the chargeback administrative fee is rounded exactly once, after the bracket has been selected (§3.9). Applying a single rounding step over a sum, or re-deriving a bracket from an already-netted amount, produces different — and wrong — answers.

Quantities are integers too, but they come in two units. An **each** (`EA`) is a single dispensable unit; a **case** (`CS`) or **box** (`BX`) contains `units_per_parent` eaches. On-hand counts and par levels are always expressed in eaches, while order quantities are expressed in the ordering unit of measure of the item being ordered. Replenishment arithmetic uses `ceil` and `floor` where the formulas in §3.3 name them, and involves no rounding mode at all.

### 2.7. Stale-Version Protection on Line Writes and Cycle Counts

Two write operations in this system are protected by optimistic concurrency control against the *parent* resource's `version`, because in both cases a repeated request would otherwise succeed silently while operating on a view of the world that has already moved.

Writing an order line — `POST /orders/{order_id}/lines` — requires a non-optional `expected_order_version` field in the request body carrying the client's last observed `version` of the target `ReplenishmentOrder`. If that value does not equal the order's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). A draft order legitimately accepts any number of lines, so a second line write is never suspicious on its own; the version check is the only signal that tells the client its picture of `order_total_cents` and of the lines already written is out of date. On success, the order's `version` advances by one, which necessarily invalidates the value the client just used.

Posting a cycle-count delta — `POST /formulary-items/{formulary_item_id}/adjust-on-hand` — requires a non-optional `expected_formulary_item_version` field carrying the client's last observed `version` of the target `FormularyItem`. A mismatch against the formulary item's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Deltas are relative, so posting the same delta twice against identical state would legitimately succeed; the version check is what stops a cycle-count client from posting a correction derived from an `on_hand_qty` that a delivery receipt has already moved. A successful adjustment advances the formulary item's `version` by one.

No other endpoint in this API accepts a version field, and none may be rejected for a version reason.

### 2.8. Two-Person Rules

Two operations in this system are subject to segregation of duties, and both are keyed on `X-User-ID` rather than on role — in each case both actors hold the same role, and it is their identity that must differ.

A `ContractAdmin` reconciling a chargeback claim must not be the same `X-User-ID` recorded in that claim's `submitted_by_user_id`. A `DistributionOperator` releasing a cold-chain excursion must not be the same `X-User-ID` recorded in that lot's `excursion_flagged_by_user_id`. Either violation is reported as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and the rule is enforced on exactly two endpoints: `POST /chargeback-claims/{chargeback_claim_id}/settle` and `POST /lots/{lot_id}/excursion`.

### 2.9. The Order in Which a Request Is Rejected

When a request violates several rules at once, the response is determined by the **first** rule to fail in the fixed order below; rules later in the order are not evaluated at all, and their error codes cannot appear. This precedence is global — it holds identically on every endpoint, and where a rule applies to only some endpoints, that scope is named alongside it.

1. **Authentication.** Both headers present, `X-User-Role` one of the five declared roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies everywhere.
2. **Role authorisation.** The acting role appears in the endpoint's role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies everywhere.
3. **Request schema.** Every required input field present, types correct, enum values inside their declared sets, integer bounds honoured (`requested_qty` greater than zero, `par_qty` greater than zero, `reorder_point` at least zero and strictly below `par_qty`, `floor_price_cents` greater than zero, `effective_to` strictly after `effective_from`, `window_open_min` at least zero and strictly below `window_close_min` which is at most 1439, `service_minutes` greater than zero, `arrival_min` between zero and 1439 inclusive), and pagination within its declared range — otherwise `ERR_VALIDATION` (400). Applies everywhere.
4. **Path existence**, left to right, per §2.5 — one of the twelve not-found codes (404). Applies to every path-templated endpoint.
5. **Body-reference existence**, per §2.5 — one of the not-found codes (404). Applies to the eleven write operations listed in §2.5.
6. **Supply-room scope** for a `MaterialsManager`, per §2.1 — `ERR_SUPPLY_ROOM_SCOPE_VIOLATION` (403). Applies to the eight operations listed in §2.1.
7. **Stale parent version**, per §2.7 — `ERR_STALE_VERSION` (412). Applies to `POST /orders/{order_id}/lines` and `POST /formulary-items/{formulary_item_id}/adjust-on-hand`.
8. **State admissibility.** The target resource's current state permits the requested transition — otherwise the state-machine code for that entity: `ERR_ORDER_NOT_DRAFT`, `ERR_ORDER_STATE_INVALID`, `ERR_ORDER_LINE_STATE_INVALID`, `ERR_CONTRACT_TRANSITION_INVALID`, `ERR_FORMULARY_STATE_INVALID`, `ERR_LOT_STATE_INVALID`, `ERR_SUBSTITUTION_STATE_INVALID`, `ERR_RECALL_STATE_INVALID`, `ERR_ROUTE_STATE_INVALID` or `ERR_CLAIM_STATE_INVALID`, all HTTP 409. Applies to every state-changing endpoint.
9. **Uniqueness**, per §3.1, §3.2, §3.3, §3.7 and §3.9 — `ERR_DUPLICATE_ROOM_CODE`, `ERR_DUPLICATE_SKU`, `ERR_DUPLICATE_CONTRACT_CODE`, `ERR_DUPLICATE_ROUTE_CODE`, `ERR_DUPLICATE_CONTRACT_LINE`, `ERR_DUPLICATE_FORMULARY_ITEM` or `ERR_CLAIM_ALREADY_OPEN`, all HTTP 409. Applies to `POST /supply-rooms`, `POST /items`, `POST /contracts`, `POST /contracts/{contract_id}/lines`, `POST /supply-rooms/{supply_room_id}/formulary-items`, `POST /delivery-routes` and `POST /chargeback-claims`.
10. **Controlled-item room eligibility** — `ERR_CONTROLLED_HANDLING_NOT_PERMITTED` (422). Applies to `POST /orders/{order_id}/submit` and `POST /substitution-requests/{substitution_request_id}/clinician-action`.
11. **Cold-chain room eligibility** — `ERR_COLD_CHAIN_ROOM_REQUIRED` (422). Applies to the same two operations as rule 10.
12. **Lot still allocatable at delivery** — `ERR_LOT_NOT_ALLOCATABLE` (422). Applies to `POST /orders/{order_id}/deliver`.
13. **Lot not expired at delivery** — `ERR_LOT_EXPIRED` (422). Applies to `POST /orders/{order_id}/deliver`.
14. **Two-person rules**, per §2.8 — `ERR_SEGREGATION_OF_DUTIES` (403). Applies to `POST /chargeback-claims/{chargeback_claim_id}/settle` and `POST /lots/{lot_id}/excursion`.
15. **Formulary standing** — `ERR_ITEM_NOT_ON_FORMULARY` (422). Applies to `POST /orders/{order_id}/lines`, `POST /orders/{order_id}/submit` and `POST /substitution-requests/{substitution_request_id}/clinician-action`.
16. **Priced by an active contract** — `ERR_NO_ACTIVE_CONTRACT_PRICE` (422). Applies to `POST /orders/{order_id}/lines`, `POST /substitution-requests/{substitution_request_id}/clinician-action` and `POST /orders/{order_id}/deliver`.
17. **Contract period overlap** — `ERR_CONTRACT_PERIOD_OVERLAP` (409). Applies to `POST /contracts/{contract_id}/transition`.
18. **Stop-to-stop collision at a room** — `ERR_ROOM_WINDOW_CONFLICT` (409). Applies to `POST /delivery-routes/{route_id}/stops`.
19. **Stop inside the room's receiving window** — `ERR_STOP_OUTSIDE_ROOM_WINDOW` (422). Applies to `POST /delivery-routes/{route_id}/stops`.
20. **Route cold-chain payload ceiling** — `ERR_ROUTE_COLD_CAPACITY_EXCEEDED` (409). Applies to `POST /delivery-routes/{route_id}/stops`.
21. **Controlled-substance quantity ceiling per order** — `ERR_CONTROLLED_QTY_LIMIT_EXCEEDED` (422). Applies to `POST /orders/{order_id}/submit`.
22. **Information-request round budget** — `ERR_SUBSTITUTION_ROUNDS_EXHAUSTED` (409). Applies to `POST /substitution-requests/{substitution_request_id}/clinician-action`.
23. **Chargeback-eligible line present** — `ERR_NO_CHARGEBACK_ELIGIBLE_LINES` (422). Applies to `POST /chargeback-claims` and `POST /chargeback-claims/{chargeback_claim_id}/settle`.
24. **Room credit limit** — `ERR_CREDIT_LIMIT_EXCEEDED` (402). Applies to `POST /orders/{order_id}/submit`.

Order submission is the sharpest illustration: it is guarded by rules 10, 11, 15, 21 and 24, and they are evaluated in exactly that ascending order for the order's open lines, so a room that is both unlicensed for controlled items and over its credit limit reports the controlled-handling failure, never the credit failure.

### 2.10. Cascades, Ledgers and the Two Order Axes

Nothing in this system settles later. When a request causes a second resource to change — a contract line blocked because its header left the active state, a lot's on-hand quantity returned because a recall unwound an allocation, a route cancelled because its last stop was detached — that change is applied inside the same request, and the affected resource's `version` and `updated_at` move accordingly. The request is likewise the unit of atomicity across clients: the server handles one request at a time — reads included — so requests never interleave, no request reads or writes the store while another is still in flight, and a request that would succeed on its own is never rejected merely because another request was being handled at the same time. `ERR_STALE_VERSION` (§2.7) is the only rejection in this system keyed on a concurrent modification.

A `ReplenishmentOrder` is the one resource with **two independent state axes**. `fulfillment_status` tracks picking and delivery and moves through `DRAFT`, `SUBMITTED`, `ALLOCATED`, `IN_TRANSIT`, `HELD`, `DELIVERED` and `CANCELLED`. `settlement_status` tracks manufacturer chargeback and moves through `UNBILLED`, `CLAIMED`, `REBILL_REQUIRED` and `RECONCILED`. Neither axis constrains the other's transition set: an order can sit at `DELIVERED` and `UNBILLED` indefinitely, and an order at `CLAIMED` can still be re-picked and re-totalled on the fulfilment axis, which is precisely what forces a rebill.

Two running ledgers must stay exact at all times. `SupplyRoom.open_commitment_cents` is the sum of `order_total_cents` over that room's orders whose `fulfillment_status` is `SUBMITTED`, `ALLOCATED`, `IN_TRANSIT` or `HELD`; it is charged at submission, adjusted by the delta whenever a submitted order's total is recomputed, and released at delivery. `GpoContract.chargeback_payable_cents` is the sum of `net_chargeback_cents` over that contract's claims whose `status` is `SUBMITTED`, `ACCEPTED` or `RECONCILED`; it is credited when a claim enters that set and debited when a claim leaves it.

## 3. Business Logic & Workflows

### 3.1. Opening a Supply Room and Populating the Item Master

A `ContractAdmin` registers each stocking location before anything can be delivered into it. Registration records the member facility it belongs to through `facility_code`, and a `room_code` that must be globally unique across every supply room in the system and between 1 and 40 characters long — a second room offered the same code is refused with `ERR_DUPLICATE_ROOM_CODE`. Two enumerations describe the room: `gpo_member_class`, one of `ACUTE`, `NON_ACUTE` or `SURGERY_CENTER`, which decides which GPO contracts are allowed to price for it, and `room_type`, one of `OR_CORE`, `ICU`, `GENERAL_STORE` or `PHARMACY_VAULT`.

Three of the room's attributes are safety attributes and they default to their most restrictive setting. `refrigerated` is false unless the room has validated 2–8 °C storage. `controlled_secured` is false unless the room has a DEA-compliant secured cabinet. `controlled_license_status` is `NONE` by default and may also be `ACTIVE` or `LAPSED`; only `ACTIVE` counts as a live licence. A room that is neither refrigerated nor secured can still be registered and can still receive ambient supplies — the attributes gate what may be ordered into it, not whether it exists.

Receiving hours are expressed as minutes past midnight. `window_open_min` is the earliest delivery minute the room will accept a stop and defaults to 360 — six o'clock in the morning; `window_close_min` is the latest minute by which a stop must have finished and defaults to 1080, six o'clock in the evening. Both must lie within a single day: the opening minute is at least zero, strictly earlier than the closing minute, and the closing minute is at most 1439. Commercially, the room carries `credit_limit_cents`, the largest open commitment it may hold at once, defaulting to 100000000 cents — one million dollars — and `open_commitment_cents`, a server-maintained figure that starts at zero and is never written directly by a client.

The item master is likewise a `ContractAdmin` responsibility. Each record carries a distributor `sku` that is globally unique (a repeat is `ERR_DUPLICATE_SKU`), a human-readable `description`, and the `manufacturer_code` that will later be matched against contracts and chargeback counterparties. `uom` is the ordering unit of measure and is one of `EA`, `BX` or `CS`; `units_per_parent` states how many eaches one such unit contains and defaults to 1, which is also its minimum, so the replenishment arithmetic in §3.3 never divides by zero. Low-unit-of-measure picking is modelled by pointing an each-level record at its case-level parent through `lum_parent_item_id`, which is null on case-level records; listing the item master filtered by that reference returns the each-level children of a case. `handling_class` — `AMBIENT`, `COLD_CHAIN`, `CONTROLLED` or `CONTROLLED_COLD` — is the storage and security class that gates which rooms may receive the item, `wac_cents` is the wholesale acquisition cost per ordering unit and must be greater than zero, `is_lot_tracked` defaults to true and marks that allocation must draw from a lot row, and `status` is `ACTIVE` by default or `DISCONTINUED`. The item master may also be listed filtered by `manufacturer_code`, by `handling_class` or by `status`.

The wholesale acquisition cost does double duty: it is the hard ceiling on any contract-derived unit price, and it is the baseline against which the manufacturer chargeback in §3.9 is computed. Setting it wrongly therefore misprices both sides of the same transaction.

### 3.2. GPO Contracts, Tier Pricing and Price Activation

A contract header is created by a `ContractAdmin` in `DRAFT`. It names the `manufacturer_code` it is written against, a globally unique `contract_code` (a repeat is `ERR_DUPLICATE_CONTRACT_CODE`), the committed-volume `tier` — `TIER_1`, `TIER_2` or `TIER_3` — and a `member_class_scope` of `ACUTE`, `NON_ACUTE` or `SURGERY_CENTER`. Only rooms whose `gpo_member_class` equals that scope may be priced by the contract. `effective_from` and `effective_to` bound the period during which the contract may price, and the interval is **closed at both ends**: an instant equal to either endpoint is inside the period. The closing instant must be strictly later than the opening one. `committed_volume_units` may be recorded on the header, defaults to zero, must not be negative, and is reported only — no rule in this system reads it. `supersedes_contract_id` optionally names the currently active contract this one is intended to replace, and is null when the contract replaces nothing. `activated_at` is null until the contract first enters the active state, and `chargeback_payable_cents` starts at zero.

Price lines hang off the header. Each line names the `item_id` it prices, a `tier_price_cents` base price per ordering unit that must be greater than zero, a `floor_price_cents` contractual floor that must also be greater than zero, and a `chargeback_eligible` flag that defaults to true and decides whether delivered quantity on that line may later be claimed back from the manufacturer. A contract may price a given item only once — a second line for the same item on the same contract is `ERR_DUPLICATE_CONTRACT_LINE`. Note that the floor is genuinely permitted to exceed the base price, in which case it binds after the tier multiplier and the handling adders have been applied. Every line is born in `activation_state` `PENDING`, and a `PENDING` line prices nothing.

The header's `status` walks `DRAFT`, `PENDING_ACTIVATION`, `ACTIVE`, `SUSPENDED`, and terminates at either `SUPERSEDED` or `EXPIRED`. A `ContractAdmin` drives it by naming a `to_status`. `DRAFT → PENDING_ACTIVATION` is permitted only from `DRAFT` and only when the contract already has at least one price line; nothing becomes usable at this step, and every line stays `PENDING`. `PENDING_ACTIVATION → ACTIVE` is permitted only from `PENDING_ACTIVATION`, only while the logical clock lies inside the closed effective period, and only when the overlap rule below passes; on success `activated_at` is set to the current logical clock and **every** line of the contract moves `PENDING → ACTIVE`, becoming selectable by the price selector. If the activating contract names a `supersedes_contract_id`, that contract moves `ACTIVE → SUPERSEDED` in the same request and, because it has left the active state, every one of *its* lines moves `ACTIVE → BLOCKED`. `ACTIVE → SUSPENDED` is permitted from `ACTIVE` at any time and moves every line `ACTIVE → BLOCKED`, which stops those lines being selectable by the price selector; already-pinned order-line prices are not rewritten by a suspension. `SUSPENDED → ACTIVE` closes the cycle: it is permitted only from `SUSPENDED`, only inside the closed effective period, and only when the overlap rule passes; it re-stamps `activated_at` and moves every line `BLOCKED → ACTIVE`. `ACTIVE → EXPIRED` is permitted only from `ACTIVE` and only once the logical clock is strictly past `effective_to`, and it moves every line `ACTIVE → BLOCKED`. Any requested `to_status` unreachable from the current status, an expiry attempted while the clock is still at or before `effective_to`, an activation attempted outside the effective period, or a move toward `PENDING_ACTIVATION` on a contract with no price line, are all `ERR_CONTRACT_TRANSITION_INVALID` (HTTP 409). `SUPERSEDED` is never requested directly; it is only ever reached as the side effect of a successor's activation.

The overlap rule that guards activation deserves its own statement, because it is the single place where two contracts can collide. Activation is refused when some **other** contract is currently `ACTIVE`, shares this contract's `manufacturer_code`, shares its `member_class_scope`, prices at least one item that this contract also prices, and has an effective interval that intersects this contract's — where intersection means this contract's `effective_from` is at or before the other's `effective_to` **and** the other's `effective_from` is at or before this contract's `effective_to`. Because both intervals are closed, two periods that merely touch at a single instant do collide. The refusal, `ERR_CONTRACT_PERIOD_OVERLAP` (HTTP 409), is waived in exactly one case: when the colliding contract is the very one named by this contract's `supersedes_contract_id`. Contracts from **different** manufacturers may legitimately be active over the same item at the same instant; the rule never fires across manufacturers, and the price selector below is what decides between them.

Pricing itself works as follows, and it is evaluated at a specific instant *T* for a specific item and a specific destination room. The candidate set is every contract line whose `item_id` matches the line's item, whose `activation_state` is `ACTIVE`, whose parent contract's `status` is `ACTIVE`, whose parent contract's `member_class_scope` equals the destination room's `gpo_member_class`, and whose parent contract's closed effective period contains *T*. Because cross-manufacturer overlap is legal, that set can genuinely hold more than one row, so ranking is fixed and total: lowest `tier_price_cents` first; ties broken by the later parent-contract `effective_from`; remaining ties broken by the earlier contract-line `created_at`. The selector never falls back to comparing identifiers. An empty candidate set is a hard failure — `ERR_NO_ACTIVE_CONTRACT_PRICE` (HTTP 422) — never a zero price.

Once the top-ranked line is chosen, its price is built in a pinned order of operations. Start from that line's `tier_price_cents` as the base. Multiply the base by the tier multiplier — `TIER_1` multiplies by 1.00, `TIER_2` by 1.06, `TIER_3` by 1.13 — and **round that product half up to a whole cent immediately**. To the rounded figure add two adders at full precision. The low-unit-of-measure adder is 12 cents, and it applies only when the item's `uom` is `EA` **and** the destination room's formulary mapping for that item has `lum_enabled` set to true; otherwise it is zero. The cold-handling adder applies only when the item's `handling_class` is `COLD_CHAIN` or `CONTROLLED_COLD`, and equals whichever is larger of 45 cents and three percent of the **unmultiplied base** rounded half up to a whole cent; otherwise it is zero. The sum of the rounded tier price and the two adders is then raised to the contract line's `floor_price_cents` if it falls below it, and only after that is it capped at the item's `wac_cents` if it exceeds it. The floor is applied before the ceiling; reversing those two steps is wrong. The result is a whole number of cents.

That one formula is used in two distinct roles, and the difference between them is the commercial heart of this system. In its **pinning** role it runs at the instant an order line is written and again at the instant a substitution is approved, storing its result in the line's `pinned_unit_price_cents` together with the identifier of the chosen line in `pinned_contract_line_id` and a copy of that line's `chargeback_eligible` flag. A pinned price survives any later supersession, suspension or expiry untouched. In its **settlement** role it runs again at the delivery instant, re-selecting the candidate set from scratch at that moment and storing its result in the line's `settled_unit_price_cents`. When the pinned contract was superseded between the line write and the delivery, the successor contract's tier and prices apply, and the settled price legitimately differs from the pinned price for otherwise identical inputs. The order total is **never** restated from settled prices, and the manufacturer chargeback uses **only** the settled price.

Contracts may be listed and filtered by `supersedes_contract_id` — which returns the successors of a given contract — by `manufacturer_code`, or by `status`. Price lines may be read individually or listed filtered by `contract_id` to walk a contract's price sheet, by `item_id` to see every contract that prices an item, or by `activation_state`.

### 3.3. Formulary Standing, Par Levels and Cycle Counts

An item is not orderable into a room merely because both exist. A `MaterialsManager` maps the item onto the room's formulary, supplying the `item_id`, the facility's own `facility_item_code` for it, a target on-hand `par_qty` in eaches that must be greater than zero, a `reorder_point` in eaches that must be at least zero and strictly below the par level, and optionally `lum_enabled`, which defaults to false and both switches on low-unit-of-measure picking and enables the per-each handling fee described in §3.2. Each room may map any given item once only; a repeat is `ERR_DUPLICATE_FORMULARY_ITEM`. A new mapping starts in `formulary_status` `REQUESTED` with `on_hand_qty` at zero and `decided_by_user_id` null, and a `REQUESTED` mapping does not permit ordering.

Clinical standing is a `Clinician`'s decision, recorded as a `decision` of `APPROVED`, `RESTRICTED` or `DELISTED`, and every decision stamps `decided_by_user_id` with the acting user. A mapping in the requested state accepts either `REQUESTED → APPROVED`, at which point the item becomes orderable into that room, or `REQUESTED → RESTRICTED`. An approved mapping accepts `APPROVED → RESTRICTED`, which refuses **new** order lines for that item into that room from then on while leaving lines already written untouched, or `APPROVED → DELISTED`. A restricted mapping accepts `RESTRICTED → APPROVED`, closing the approve-and-restrict cycle, or `RESTRICTED → DELISTED`. `DELISTED` is terminal: any decision requested against a delisted mapping, and any decision requested from a state that does not permit it, is `ERR_FORMULARY_STATE_INVALID` (HTTP 409).

On-hand counts move in two ways. Deliveries increase them, as described in §3.7. Cycle counts adjust them: a `MaterialsManager` posts a `delta_qty`, which may be negative, together with the `expected_formulary_item_version` described in §2.7. The delta is added to `on_hand_qty` and the result is floored at zero, so a correction larger than the count on hand leaves zero rather than a negative figure, and the mapping's `version` advances by one.

Replenishment suggestions are a pure projection: they read a mapping, compute a recommendation, persist nothing, and are available to both a `MaterialsManager` for its own room and to a `ContractAdmin`. Eligibility is a two-part gate — the mapping's `formulary_status` must be `APPROVED` **and** its `on_hand_qty` must be less than or equal to its `reorder_point`. The boundary is inclusive: a count exactly equal to the reorder point **is** due for replenishment, while a count one greater is not. When the gate fails, the response reports `eligible` as false and `deficit_eaches`, `suggested_case_qty`, `suggested_each_qty` and `suggested_total_eaches` all as zero. When it passes, `eligible` is true and the deficit is the par level minus the on-hand count, in eaches.

How that deficit is turned into a pick depends on the `variant` requested, and the response echoes the requested variant back. Under `STANDARD_TOPOFF`, only whole cases may be picked: the suggested case quantity is the deficit in eaches divided by the item's `units_per_parent`, **rounded up** to the next whole case; the suggested each quantity is zero; and the suggested total in eaches is the case quantity multiplied by `units_per_parent`. This over-ships whenever the deficit is not an exact multiple of the case size. Under `LUM_SPLIT`, cases and loose eaches may be mixed: the suggested case quantity is the deficit divided by `units_per_parent` **rounded down** to a whole case; the suggested each quantity is whatever remains after removing those whole cases from the deficit; and the suggested total in eaches equals the deficit exactly. For a mapping with a par level of 100 eaches, 30 eaches on hand and 24 eaches to a case, the two variants disagree by design: whole-case top-off suggests 3 cases and 72 eaches, while the split variant suggests 2 cases plus 22 loose eaches and 70 eaches in total.

Formulary mappings may be listed filtered by `supply_room_id` to walk one room's formulary, by `item_id` to find every room stocking an item, or by `formulary_status`.

### 3.4. Writing, Totalling and Submitting a Replenishment Order

A `MaterialsManager` opens an order against its own room by naming the `supply_room_id`. The new order is born with `fulfillment_status` `DRAFT`, `settlement_status` `UNBILLED`, `order_total_cents` at zero, and `route_id`, `stop_arrival_min`, `stop_service_minutes`, `service_date`, `submitted_at` and `delivered_at` all null.

Lines are written onto the order while it is still `DRAFT` — a line write against an order in any other fulfilment state is `ERR_ORDER_NOT_DRAFT` (HTTP 409). A line write names the `item_id`, the `requested_qty` in the item's ordering unit of measure (which must be greater than zero), and the `expected_order_version` demanded by §2.7. Before the line is accepted, the item must already be `APPROVED` on the destination room's formulary — otherwise `ERR_ITEM_NOT_ON_FORMULARY` (HTTP 422) — and the price selector of §3.2 must find a candidate, otherwise `ERR_NO_ACTIVE_CONTRACT_PRICE` (HTTP 422). What the room is physically licensed to store is deliberately **not** checked here: a draft order is a worksheet, and the controlled-item and cold-chain room gates run at submission and at substitution approval, never at line write.

An accepted line is created in `line_status` `OPEN` with `lot_id` null, `allocated_qty` zero and `settled_unit_price_cents` null. Pinning writes `pinned_unit_price_cents`, `pinned_contract_line_id` and the line's own `chargeback_eligible` copy, and the order's `version` advances by one.

Totalling then runs over the whole order, and the order of operations is pinned. Only lines whose `line_status` is `OPEN`, `ALLOCATED`, `SUBSTITUTED` or `DELIVERED` participate; lines that are `BACKORDERED`, `SHORTED` or `CANCELLED` are excluded and have their `extended_price_cents` and `line_fee_cents` set to zero. Each participating line contributes on a quantity basis that depends on its state: `allocated_qty` when the line is `ALLOCATED` or `DELIVERED`, and `requested_qty` when it is `OPEN` or `SUBSTITUTED`. For each participating line the extended price is its `pinned_unit_price_cents` multiplied by that quantity basis, and the line fee is the distribution fee of 2.75 percent applied to that extended price and **rounded half up to a whole cent on that line, before anything is summed**. The order's `order_total_cents` is the sum, over the participating lines, of extended price plus line fee. Summing the extended prices first and rounding a single fee over the sum is explicitly wrong and produces a different answer: two lines each extending to 200 cents total 412 cents per-line-rounded, and 411 cents if the fee is rounded once over the sum. Totalling re-runs on every event that can change a line — line writes, allocation, delivery, substitution approvals and rejections, and the recall cascade — and always follows the same order.

Submission moves the order `DRAFT → SUBMITTED`. It requires the order to still be `DRAFT` — a submission attempted on an order in any other fulfilment state is `ERR_ORDER_NOT_DRAFT` — and to carry at least one `OPEN` line, and it is guarded by five business gates evaluated in the ascending order given in §2.9, so the first one to fail is the one reported. First, **controlled-item eligibility**: for every non-terminal line — that is, every line whose `line_status` is `OPEN`, `ALLOCATED`, `BACKORDERED` or `SUBSTITUTED` — whose item's `handling_class` is `CONTROLLED` or `CONTROLLED_COLD`, the destination room must have `controlled_secured` true **and** `controlled_license_status` equal to `ACTIVE`; otherwise `ERR_CONTROLLED_HANDLING_NOT_PERMITTED` (HTTP 422). Second, **cold-chain eligibility**: for every non-terminal line whose item's `handling_class` is `COLD_CHAIN` or `CONTROLLED_COLD`, the room must have `refrigerated` true; otherwise `ERR_COLD_CHAIN_ROOM_REQUIRED` (HTTP 422). Third, **formulary standing** is re-checked for every open line, because a clinician may have restricted or delisted a mapping since the line was written; a failure is `ERR_ITEM_NOT_ON_FORMULARY`. Fourth, **the controlled-substance ceiling**: the total `requested_qty` across all non-terminal lines whose items are `CONTROLLED` or `CONTROLLED_COLD` must be at most 100 units on a single order, and exceeding it is `ERR_CONTROLLED_QTY_LIMIT_EXCEEDED` (HTTP 422). Fifth, **the room's credit limit**: the room's current `open_commitment_cents` plus this order's `order_total_cents` must be less than or equal to its `credit_limit_cents`, and a breach is `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

On a successful submission, `submitted_at` is stamped with the logical clock and the order's `order_total_cents` is added to the room's `open_commitment_cents`. From that moment the room is committed for the money until the order is delivered or its lines fall away.

Orders may be listed filtered by `supply_room_id` for a room's book, by `route_id` for a route's manifest, by `fulfillment_status` or by `settlement_status`, and a single order read shows both axes and its total. Order lines may be read individually — showing both the pinned and the settled unit price — or listed filtered by `order_id`, by `item_id`, by `lot_id` to find every line drawn from a given lot, by `pinned_contract_line_id` to find every line priced off a given contract line, or by `line_status`.

### 3.5. Lots, Cold-Chain Excursions and FEFO Picking

A `DistributionOperator` receives manufacturer stock as a lot, naming the `item_id` it holds, the manufacturer's `lot_code`, an `expiry_date` and a `received_quantity` in the item's ordering unit of measure, which must be greater than zero. The received quantity is immutable once written and anchors a units-conservation invariant: at every instant, the lot's `quantity_on_hand` plus the quantity currently allocated out of it to order lines must equal the received quantity, unless the lot has been written off. A new lot begins with `quantity_on_hand` equal to `received_quantity`, `status` `AVAILABLE` and `excursion_flagged_by_user_id` null.

Temperature excursions are handled by a single three-way capability that takes an `action` of `FLAG`, `RELEASE` or `DESTROY` and an optional `note`. Flagging moves an `AVAILABLE` lot to `EXCURSION_HOLD`, records the acting operator in `excursion_flagged_by_user_id`, and removes the lot from consideration for picking. Releasing moves an `EXCURSION_HOLD` lot back to `AVAILABLE` and clears `excursion_flagged_by_user_id` — and this is where the two-person rule of §2.8 bites: an operator may not release the excursion they themselves flagged, and an attempt is `ERR_SEGREGATION_OF_DUTIES`. That pairing closes the `AVAILABLE → EXCURSION_HOLD → AVAILABLE` cycle. Destroying is permitted as `EXCURSION_HOLD → DESTROYED` and as `QUARANTINED → DESTROYED`, and in both cases zeroes `quantity_on_hand`; the `EXCURSION_HOLD → DESTROYED` branch additionally clears `excursion_flagged_by_user_id`. `DESTROYED` is terminal. Any of the three actions requested from a lot status that does not permit it is `ERR_LOT_STATE_INVALID` (HTTP 409). The two remaining lot transitions — `AVAILABLE → QUARANTINED` and `EXCURSION_HOLD → QUARANTINED` — are never requested directly; they occur only inside the recall cascade of §3.8, and the second of them also clears `excursion_flagged_by_user_id`.

Picking is a `DistributionOperator` action against a submitted or held order, and it runs a **first-expiry-first-out** selector line by line. For a given line, a lot is a candidate when it holds the line's item, its `status` is `AVAILABLE`, its `expiry_date` is strictly later than the current logical clock, and its `quantity_on_hand` is at least the quantity the line needs; among candidates the lot with the earliest `expiry_date` wins, and if two lots expire at the same instant the one created earlier wins. Allocation is all-or-nothing per line: a line either takes its full quantity from one lot or takes nothing.

From `SUBMITTED`, picking moves the order `SUBMITTED → ALLOCATED` when at least one of its lines finds a lot. Each `OPEN` or `SUBSTITUTED` line that finds a lot moves `OPEN → ALLOCATED` or `SUBSTITUTED → ALLOCATED` respectively, records `lot_id` and `allocated_qty`, decrements that lot's `quantity_on_hand` by the allocated quantity, and has its `extended_price_cents` and `line_fee_cents` recomputed. Each `OPEN` or `SUBSTITUTED` line that finds no lot moves to the backordered state — `OPEN → BACKORDERED` for a line that had never been picked — and has its extended price and line fee zeroed, because backordered lines leave the total. If **no** line finds a lot at all, the order moves `SUBMITTED → HELD` instead, every `OPEN` line becomes `BACKORDERED`, and the recomputed `order_total_cents` is therefore zero. A held order can be picked again: it takes `HELD → ALLOCATED` as soon as at least one `BACKORDERED` or `SUBSTITUTED` line finds a lot, with matching lines moving `BACKORDERED → ALLOCATED` or `SUBSTITUTED → ALLOCATED`. Every picking run recomputes `order_total_cents` and adjusts the room's `open_commitment_cents` by the change in that total. Picking requested from any other fulfilment state is `ERR_ORDER_STATE_INVALID` (HTTP 409).

Lots may be read individually or listed filtered by `item_id` to see every lot of an item, or by `status`.

### 3.6. Backorders and Clinician-Approved Substitution

When a line cannot be filled, the materials manager may propose an alternative. A substitution request names the `proposed_item_id` and carries a free-text `justification`, and it is permitted while the target line is either `OPEN` or `BACKORDERED` — a request opened against a line in any other state is `ERR_ORDER_LINE_STATE_INVALID` (HTTP 409). The new request records `requested_by_user_id` from the acting user, starts in `status` `PENDING` with `rounds_used` at zero, and leaves `clinician_user_id`, `info_request_note`, `response_note` and `price_delta_cents` null.

A `Clinician` decides the request through an `action` of `REQUEST_INFO`, `APPROVE` or `REJECT`, optionally attaching a `note`. `REQUEST_INFO` is permitted only from `PENDING`, moves the request to `INFO_REQUESTED`, stores the supplied note as `info_request_note` and stamps `clinician_user_id`. It is budgeted: a clinician may open a round only while `rounds_used` is strictly less than 2, and an attempt once that ceiling has been reached is `ERR_SUBSTITUTION_ROUNDS_EXHAUSTED` (HTTP 409). The requester answers with an `action` of `RESPOND` and a `response_note`, which is permitted only from `INFO_REQUESTED`, stores the note, increments `rounds_used` by one, and returns the request to `PENDING` — closing the `PENDING → INFO_REQUESTED → PENDING` cycle under a bounded counter. A `RESPOND` attempted while the request is already `PENDING`, and any clinician action or requester response against a request already in `APPROVED`, `REJECTED` or `WITHDRAWN`, is `ERR_SUBSTITUTION_STATE_INVALID` (HTTP 409).

Approval is the consequential branch. It is permitted only from `PENDING`, and only when the target line is `BACKORDERED` (an approval aimed at a line in any other state is `ERR_ORDER_LINE_STATE_INVALID`), when a formulary mapping for the destination room and the **proposed** item exists in `APPROVED` standing, and when the price selector resolves an active contract line for the proposed item at the current logical clock. The room-eligibility gates apply to the proposed item exactly as they do at submission: a controlled or controlled-cold substitute into a room lacking `controlled_secured` or an `ACTIVE` `controlled_license_status` is `ERR_CONTROLLED_HANDLING_NOT_PERMITTED`, a cold-chain or controlled-cold substitute into an unrefrigerated room is `ERR_COLD_CHAIN_ROOM_REQUIRED`, a proposed item not `APPROVED` on that room's formulary is `ERR_ITEM_NOT_ON_FORMULARY`, and an unpriced proposed item is `ERR_NO_ACTIVE_CONTRACT_PRICE`. On success the request moves `PENDING → APPROVED`, stamps `clinician_user_id`, and rewrites the target line in place: the line's `item_id` becomes the proposed item, and `pinned_contract_line_id`, `pinned_unit_price_cents` and `chargeback_eligible` are re-pinned by the pinning role of the price formula at the current instant. The request records `price_delta_cents` as the new pinned unit price minus the previously pinned unit price — a negative figure when the substitute is cheaper. The line moves `BACKORDERED → SUBSTITUTED`, and because a substituted line participates in the total on its `requested_qty` basis, `extended_price_cents`, `line_fee_cents` and the order's `order_total_cents` are all recomputed. That recomputation has a settlement consequence: if the order was sitting at `settlement_status` `CLAIMED` when its total changed, the order moves `CLAIMED → REBILL_REQUIRED`, its open claim moves `SUBMITTED → REBILL_REQUIRED`, and the claim's `net_chargeback_cents` is subtracted from the contract's `chargeback_payable_cents`.

Rejection is permitted as `PENDING → REJECTED` and as `INFO_REQUESTED → REJECTED`. It stamps `clinician_user_id` and moves the target line `BACKORDERED → SHORTED`. A shorted line leaves the order permanently: it never re-enters `order_total_cents` and can never be picked again.

Withdrawal belongs to the requester and is permitted as `PENDING → WITHDRAWN` and as `INFO_REQUESTED → WITHDRAWN`. If the target line is still `OPEN` at that moment, the line moves `OPEN → CANCELLED` with its extended price and line fee zeroed. And if that cancellation leaves a `DRAFT` order with every one of its lines in `CANCELLED`, the order itself moves `DRAFT → CANCELLED` with `order_total_cents` set to zero — the only path to a cancelled order in this system, reached by cascade rather than by any direct request.

Substitution requests may be read individually or listed filtered by `order_line_id`, by `proposed_item_id`, or by `status`.

### 3.7. Routing, Dispatch and Receipt into the Supply Room

Delivery is planned as a dated route. A `DistributionOperator` plans one by naming a globally unique `route_code` — a repeat is `ERR_DUPLICATE_ROUTE_CODE` — a `service_date` in `YYYY-MM-DD` form, and a `vehicle_class` of either `AMBIENT_VAN` or `REEFER_VAN`. The route starts `PLANNED`, with `planned_order_count` and `cold_units_loaded` at zero and `dispatched_at` null.

Allocated orders are then attached to the route as timed stops. A stop names the `order_id`, an `arrival_min` giving the minute of day at which the stop begins (between 0 and 1439 inclusive), and a `service_minutes` duration greater than zero. The route must still be `PLANNED` — otherwise `ERR_ROUTE_STATE_INVALID` — and the order must be `ALLOCATED` — otherwise `ERR_ORDER_STATE_INVALID`. Three geometry and capacity rules then apply, in this order.

The first is stop-to-stop separation at the destination room. A stop occupies the **half-open** interval that begins at its arrival minute and ends immediately before its arrival minute plus its service duration, and the room additionally demands a 15-minute turnover between consecutive stops. Two stops at the same supply room on the same service date, on any route whose `status` is `PLANNED` or `DISPATCHED`, collide when the new stop's arrival minute is earlier than the existing stop's arrival minute plus the existing stop's service duration plus 15, **and** the existing stop's arrival minute is earlier than the new stop's arrival minute plus the new stop's service duration plus 15. A collision is `ERR_ROOM_WINDOW_CONFLICT` (HTTP 409).

The second is the room's own receiving window: the arrival minute must be at or after the room's `window_open_min`, and the arrival minute plus the service duration must be at or before its `window_close_min`. A stop that starts too early or runs past closing is `ERR_STOP_OUTSIDE_ROOM_WINDOW` (HTTP 422).

The third is the aggregate cold-chain payload. A route's `cold_units_loaded` is the sum of `allocated_qty` over every line, of every order currently assigned to the route whose `fulfillment_status` is `ALLOCATED`, `IN_TRANSIT` or `DELIVERED`, where the line's own `line_status` is `ALLOCATED` or `DELIVERED` and its item's `handling_class` is `COLD_CHAIN` or `CONTROLLED_COLD`; `planned_order_count` counts the assigned orders in those same three fulfilment states. The gate is evaluated as a **projection before** the stop is written: the route's current cold units plus the incoming order's cold units, computed the same way, must not exceed the vehicle's capacity. A `REEFER_VAN` carries at most 400 cold units; an `AMBIENT_VAN` has an effective cold capacity of zero, so any incoming order carrying cold units at all is refused. Exceeding either ceiling is `ERR_ROUTE_COLD_CAPACITY_EXCEEDED` (HTTP 409); a projection exactly equal to the ceiling is accepted.

An accepted stop writes `route_id`, `stop_arrival_min` and `stop_service_minutes` onto the order and copies the route's `service_date` onto it, then recomputes the route's `planned_order_count` and `cold_units_loaded`. The response is the updated order rather than the route.

Dispatch moves the route `PLANNED → DISPATCHED`. It requires the route to be `PLANNED`, to carry at least one assigned order, and for **every** assigned order to be `ALLOCATED`; a dispatch attempted on a route that is not planned, on an empty route, or on a route holding an order in any other fulfilment state, is `ERR_ROUTE_STATE_INVALID`. On success `dispatched_at` is stamped with the logical clock and every assigned order moves `ALLOCATED → IN_TRANSIT`. No price is recomputed at dispatch.

Receipt into the room moves the order `IN_TRANSIT → DELIVERED` and is where the second pricing pass happens; a delivery attempted from any other fulfilment state is `ERR_ORDER_STATE_INVALID`. Before anything is written, every `ALLOCATED` line's lot is re-examined: its `status` must still be `AVAILABLE`, otherwise `ERR_LOT_NOT_ALLOCATABLE` (HTTP 422), and its `expiry_date` must be strictly later than the current logical clock, otherwise `ERR_LOT_EXPIRED` (HTTP 422). The settlement role of the price formula then re-selects a contract for each line at the delivery instant and writes `settled_unit_price_cents`; a line for which no active contract line resolves at that instant is `ERR_NO_ACTIVE_CONTRACT_PRICE`. Every `ALLOCATED` line moves `ALLOCATED → DELIVERED`. For each delivered line the destination formulary mapping's `on_hand_qty` increases by the line's `allocated_qty` multiplied by the item's `units_per_parent` when the item's `uom` is `CS`, and by one otherwise — an each-level or box-level line adds its allocated quantity unchanged. The order's `delivered_at` is stamped, and its `order_total_cents` is subtracted from the room's `open_commitment_cents`, releasing the credit. Finally, if every order assigned to the carrying route is now `DELIVERED`, the route moves `DISPATCHED → COMPLETED` and its `planned_order_count` is left at its final value. `order_total_cents` is never restated from the settled prices.

Routes may be read individually — showing their stop counters and cold load — or listed filtered by `status` or by `service_date`.

### 3.8. Recall and Lot Notification Cascade

A `ContractAdmin` issues a recall by naming the recalled `item_id`, a `recall_class` of `CLASS_I`, `CLASS_II` or `CLASS_III`, and a `reason`. An optional `lot_id` narrows the notice to a single lot; when it is omitted, every lot of the item is in scope. A new notice is `ISSUED`, with `quarantined_lot_count` and `backordered_line_count` at zero and `cascaded_at` null — issuing a notice quarantines nothing, and this separation is deliberate, so that the notification can be reviewed before it moves stock.

Cascading is a `DistributionOperator` action carrying an `action` of `CASCADE` or `CLOSE`. `CASCADE` is permitted only from `ISSUED` and drives `ISSUED → CASCADED`; `CLOSE` is permitted only from `CASCADED` and drives `CASCADED → CLOSED`, touching no lot and no line. Either action requested from the wrong state is `ERR_RECALL_STATE_INVALID` (HTTP 409).

The cascade itself runs four hops, in order, inside the one request.

**Hop one — lots.** Every lot holding the recalled item, matching the notice's `lot_id` when one was given, whose `status` is `AVAILABLE` or `EXCURSION_HOLD`, is moved to `QUARANTINED`, processing lots in ascending `created_at` order. A lot that was on excursion hold also has its `excursion_flagged_by_user_id` cleared. The number of lots moved is written to `quarantined_lot_count`.

**Hop two — order lines.** Because a lot became quarantined, every order line drawn from that lot whose `line_status` is `ALLOCATED` is moved `ALLOCATED → BACKORDERED`, processing lines in ascending `created_at` order. Each such line returns its `allocated_qty` to the lot's `quantity_on_hand`, then clears its `lot_id` and sets `allocated_qty` to zero, and has its `extended_price_cents` and `line_fee_cents` zeroed because a backordered line leaves the total. The number of lines moved is written to `backordered_line_count`.

**Hop three — orders.** Because a line became backordered, its parent order recomputes `order_total_cents`, and the destination room's `open_commitment_cents` is adjusted by the change in that total. If every line of that order is now `BACKORDERED`, `SHORTED` or `CANCELLED` and the order's `fulfillment_status` is `ALLOCATED`, the order moves `ALLOCATED → HELD`.

**Hop four — routes.** Because an order moved to held, if it was carrying a `route_id` the order is detached from its route: `route_id`, `stop_arrival_min`, `stop_service_minutes` and `service_date` are all cleared, and the route recomputes `planned_order_count` and `cold_units_loaded`. If that recomputation leaves a `PLANNED` route with no assigned orders at all, the route moves `PLANNED → CANCELLED` and its `cold_units_loaded` is set to zero.

When the four hops have run, `cascaded_at` is stamped with the logical clock. Recall notices may be read individually with their cascade counters, or listed filtered by `item_id`, by `lot_id`, or by `status`.

### 3.9. Manufacturer Chargeback Settlement

A chargeback recovers, from the manufacturer, the difference between the list acquisition cost of what was delivered and the contracted price the facility actually paid. A `ContractAdmin` raises the claim by naming the delivered `order_id` and the `contract_id` it settles against. The order must have `fulfillment_status` `DELIVERED` and `settlement_status` `UNBILLED`; an order may carry at most one claim whose `status` is anything other than `DISPUTED`, and a second is `ERR_CLAIM_ALREADY_OPEN` (HTTP 409).

The claim's arithmetic runs over a strictly defined set: those lines of the claimed order whose `line_status` is `DELIVERED` **and** whose `chargeback_eligible` flag is true. Lines in any other status, and delivered lines that were pinned against a contract line that was not chargeback-eligible, are excluded. `eligible_line_count` records the size of that set, and an empty set is a hard rejection rather than a zero-value claim: `ERR_NO_CHARGEBACK_ELIGIBLE_LINES` (HTTP 422).

The settlement is computed in four pinned steps, because the fee bracket and the amount it applies to would otherwise be mutually defining. **Step one:** `gross_chargeback_cents` is the sum, over the eligible lines, of the item's `wac_cents` minus that line's `settled_unit_price_cents`, floored at zero for each line individually, multiplied by that line's `allocated_qty` — a line settled above the wholesale acquisition cost contributes nothing rather than a negative amount, and the *settled* price is used, never the pinned one. **Step two:** `admin_fee_pct` is selected from a bracket keyed on the gross amount — a gross below 50000 cents takes 0.020, a gross from 50000 cents up to but not including 250000 cents takes 0.015, and a gross of 250000 cents or more takes 0.010. Bracket edges are inclusive on the lower bound, so a gross of exactly 50000 cents takes the middle rate of 0.015. **Step three:** `admin_fee_cents` is the gross multiplied by the selected rate, rounded half up to a whole cent — this is the only rounding step in the whole settlement. **Step four:** `net_chargeback_cents` is the gross minus the administrative fee. The bracket is keyed on the gross figure and is never re-derived from the net figure; re-keying after step four changes the answer whenever the net amount falls into a different bracket than the gross did.

Creating the claim stores all five computed figures, records `submitted_by_user_id` from the acting administrator, starts the claim in `SUBMITTED` with `reconciled_by_user_id` and `dispute_reason` null, adds its `net_chargeback_cents` to the contract's `chargeback_payable_cents`, and moves the order `UNBILLED → CLAIMED` on its settlement axis.

The manufacturer responds through a `ManufacturerRep` supplying an `outcome` of `ACCEPT` or `DISPUTE`, and either is permitted only while the claim is `SUBMITTED`. `ACCEPT` moves the claim `SUBMITTED → ACCEPTED` and leaves the contract ledger untouched, because an accepted claim remains inside the payable set. `DISPUTE` moves the claim `SUBMITTED → DISPUTED`, records the supplied `dispute_reason`, subtracts the claim's `net_chargeback_cents` from the contract's `chargeback_payable_cents`, and returns the order's settlement axis `CLAIMED → UNBILLED`.

The distributor settles through a `ContractAdmin` supplying an `action` of `RECONCILE` or `RESUBMIT`. `RECONCILE` is permitted only while the claim is `ACCEPTED`; it is subject to the two-person rule of §2.8, so the acting `X-User-ID` must differ from `submitted_by_user_id`, and a violation is `ERR_SEGREGATION_OF_DUTIES`. It moves the claim `ACCEPTED → RECONCILED`, records `reconciled_by_user_id`, leaves the ledger untouched because a reconciled claim also remains inside the payable set, and moves the order `CLAIMED → RECONCILED`. `RECONCILED` is terminal on both the claim and the order's settlement axis. `RESUBMIT` is permitted from `DISPUTED` and from `REBILL_REQUIRED`; in both cases the four settlement steps are re-run at the current logical clock, rewriting `gross_chargeback_cents`, `admin_fee_pct`, `admin_fee_cents`, `net_chargeback_cents` and `eligible_line_count`, and the recomputed net amount is added back to the contract's `chargeback_payable_cents`. Resubmitting a disputed claim moves it `DISPUTED → SUBMITTED` and the order `UNBILLED → CLAIMED`, closing the dispute cycle; resubmitting a rebill-required claim moves it `REBILL_REQUIRED → SUBMITTED` and the order `REBILL_REQUIRED → CLAIMED`. A resubmission is subject to the same eligible-line requirement as an original claim. Any response or settle action requested from a claim status that does not permit it is `ERR_CLAIM_STATE_INVALID` (HTTP 409).

One transition on this axis is never requested by anyone. When a claimed order's `order_total_cents` changes — because a substitution was approved, a rejection shorted a line, a recall backordered a line, or a re-pick re-totalled the order — the order moves `CLAIMED → REBILL_REQUIRED`, its open claim moves `SUBMITTED → REBILL_REQUIRED`, and the claim's `net_chargeback_cents` is subtracted from the contract's `chargeback_payable_cents`. The claim then sits waiting for a resubmission, which is the only way back to `CLAIMED`.

Claims may be read individually with their full settlement breakdown, or listed filtered by `order_id`, by `contract_id`, or by `status`.

## 4. Endpoint Definitions

Every endpoint below is mounted at the server root; there is no additional path prefix. Creating a new resource returns HTTP 201 with the created resource in `data`; every other successful operation — reads, list reads, state transitions, computed projections and the clock control — returns HTTP 200. Requests that mutate state return the resource they conceptually act on, which for a route stop is the updated order rather than the route. The request payload each endpoint expects, and the side effects each one triggers, are specified in the narratives of §2 and §3; the table below fixes only the HTTP contract and the roles allowed to invoke it. "All roles" in the last column means all five roles named in §2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/supply-rooms` | Register a supply room at a member facility. | `ContractAdmin` |
| GET | `/supply-rooms/{supply_room_id}` | Read one supply room. | All roles |
| POST | `/items` | Create an item-master record. Supply lum_parent_item_id to declare this each-level item as the low-unit-of-measure breakdown of a case-level item. | `ContractAdmin` |
| GET | `/items/{item_id}` | Read one item-master record. | All roles |
| GET | `/items` | List item-master records. Filtering by lum_parent_item_id returns the each-level children of a case-level item. | All roles |
| POST | `/contracts` | Create a GPO contract header in DRAFT. | `ContractAdmin` |
| GET | `/contracts/{contract_id}` | Read one GPO contract, including its running chargeback_payable_cents ledger. | All roles |
| GET | `/contracts` | List GPO contracts. Filtering by supersedes_contract_id returns the successors of a given contract. | All roles |
| POST | `/contracts/{contract_id}/transition` | Drive the contract status machine: PENDING_ACTIVATION, ACTIVE, SUSPENDED or EXPIRED. | `ContractAdmin` |
| POST | `/contracts/{contract_id}/lines` | Add a per-item contracted price to a contract. The line starts PENDING and only becomes selectable when the contract activates. | `ContractAdmin` |
| GET | `/contract-lines/{contract_line_id}` | Read one contract line. | All roles |
| GET | `/contract-lines` | List contract lines. Filter by contract_id to walk a contract's price sheet, or by item_id to see every contract that prices an item. | All roles |
| POST | `/supply-rooms/{supply_room_id}/formulary-items` | Map an item onto a supply room's formulary and configure its par level. Starts REQUESTED and is not orderable until a clinician approves it. | `MaterialsManager` |
| GET | `/formulary-items/{formulary_item_id}` | Read one formulary mapping with its par configuration and on-hand count. | All roles |
| GET | `/formulary-items` | List formulary mappings. Filter by supply_room_id for a room's formulary or by item_id for every room stocking an item. | All roles |
| POST | `/formulary-items/{formulary_item_id}/decision` | Record a clinician formulary decision: APPROVED, RESTRICTED or DELISTED. | `Clinician` |
| POST | `/formulary-items/{formulary_item_id}/adjust-on-hand` | Post a cycle-count delta against the room's on-hand quantity. Optimistically concurrent on the formulary item's version. | `MaterialsManager` |
| GET | `/formulary-items/{formulary_item_id}/replenishment-suggestion` | Computed read. Returns the par-level replenishment suggestion under the requested variant (STANDARD_TOPOFF whole cases, or LUM_SPLIT cases plus loose eaches). Persists nothing. | `MaterialsManager`, `ContractAdmin` |
| POST | `/lots` | Receive a manufacturer lot into the distribution centre. | `DistributionOperator` |
| GET | `/lots/{lot_id}` | Read one lot. | All roles |
| GET | `/lots` | List lots. Filter by item_id to see every lot of an item. | All roles |
| POST | `/lots/{lot_id}/excursion` | Cold-chain excursion handling: FLAG places the lot on hold, RELEASE returns it to AVAILABLE under a two-person rule, DESTROY writes it off. | `DistributionOperator` |
| POST | `/orders` | Open a DRAFT replenishment order for a supply room. | `MaterialsManager` |
| GET | `/orders/{order_id}` | Read one replenishment order, including both state axes and order_total_cents. | All roles |
| GET | `/orders` | List replenishment orders. Filter by supply_room_id for a room's orders or by route_id for a route's manifest. | All roles |
| POST | `/orders/{order_id}/lines` | Write a line onto a DRAFT order. Pins the unit price from the contract ACTIVE at this instant. Optimistically concurrent on the order's version. | `MaterialsManager` |
| POST | `/orders/{order_id}/submit` | Submit a DRAFT order for picking. | `MaterialsManager` |
| POST | `/orders/{order_id}/allocate` | Run FEFO lot allocation over the order's OPEN, BACKORDERED and SUBSTITUTED lines. | `DistributionOperator` |
| POST | `/orders/{order_id}/deliver` | Receive an in-transit order into the supply room. Re-prices every allocated line against the contract ACTIVE at the delivery instant. | `DistributionOperator` |
| GET | `/order-lines/{order_line_id}` | Read one order line, including both the pinned and the settled unit price. | All roles |
| GET | `/order-lines` | List order lines. Filter by order_id, by item_id, by lot_id to find every line drawn from a lot, or by pinned_contract_line_id to find every line priced off a contract line. | All roles |
| POST | `/order-lines/{order_line_id}/substitution-requests` | Propose a substitute item for an order line, for clinician decision. Permitted while the line is OPEN or BACKORDERED; approval itself still requires BACKORDERED. | `MaterialsManager` |
| GET | `/substitution-requests/{substitution_request_id}` | Read one substitution request. | All roles |
| GET | `/substitution-requests` | List substitution requests. Filter by order_line_id or by proposed_item_id. | All roles |
| POST | `/substitution-requests/{substitution_request_id}/clinician-action` | Clinician decision on a substitution: REQUEST_INFO opens another round, APPROVE swaps the line's item and re-pins its price, REJECT shorts the line. | `Clinician` |
| POST | `/substitution-requests/{substitution_request_id}/respond` | Requester follow-up: RESPOND answers an information request and returns the case to PENDING, WITHDRAW closes it. | `MaterialsManager` |
| POST | `/recall-notices` | Issue a manufacturer recall on an item, optionally narrowed to a single lot. | `ContractAdmin` |
| GET | `/recall-notices/{recall_notice_id}` | Read one recall notice with its cascade counters. | All roles |
| GET | `/recall-notices` | List recall notices. Filter by item_id or lot_id. | All roles |
| POST | `/recall-notices/{recall_notice_id}/cascade` | CASCADE quarantines every in-scope lot and unwinds the four-hop notification chain into order lines, orders and routes. CLOSE ends the notice. | `DistributionOperator` |
| POST | `/delivery-routes` | Plan a dated delivery route. | `DistributionOperator` |
| GET | `/delivery-routes/{route_id}` | Read one route with its stop counters and cold-chain load. | All roles |
| GET | `/delivery-routes` | List delivery routes. | All roles |
| POST | `/delivery-routes/{route_id}/stops` | Add an allocated order to the route as a timed stop at its supply room. Enforces the room window, the half-open stop geometry with turnover buffer, and the aggregate cold-chain ceiling. Returns the updated order. | `DistributionOperator` |
| POST | `/delivery-routes/{route_id}/dispatch` | Dispatch the route; every assigned order moves ALLOCATED -> IN_TRANSIT. | `DistributionOperator` |
| POST | `/chargeback-claims` | Raise a chargeback claim against a manufacturer contract for a delivered order's eligible lines. | `ContractAdmin` |
| GET | `/chargeback-claims/{chargeback_claim_id}` | Read one chargeback claim with its full settlement breakdown. | All roles |
| GET | `/chargeback-claims` | List chargeback claims. Filter by order_id or contract_id. | All roles |
| POST | `/chargeback-claims/{chargeback_claim_id}/response` | Manufacturer response to a submitted claim: ACCEPT or DISPUTE. | `ManufacturerRep` |
| POST | `/chargeback-claims/{chargeback_claim_id}/settle` | Distributor settlement action: RECONCILE closes an accepted claim under the two-person rule, RESUBMIT recomputes and re-posts a disputed or rebill-required claim. | `ContractAdmin` |
| POST | `/_clock/set_current_utc` | Set the server's logical clock. The clock starts at exactly 2026-08-01T00:00:00Z on server start and never falls back to wall-clock time; every effective-date, expiry and delivery timestamp in this API reads from it. | `ContractAdmin` |

## 5. Error Code Catalogue

Each error is returned inside the standard error envelope of §2.2, with the identifier below in `error_id`. The conditions that raise each code are stated in the narratives of §2 and §3, alongside the rules they enforce; the precedence between them when several would apply at once is fixed by §2.9.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_SUPPLY_ROOM_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_SUPPLY_ROOM_NOT_FOUND` | 404 |
| `ERR_ITEM_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_CONTRACT_LINE_NOT_FOUND` | 404 |
| `ERR_FORMULARY_ITEM_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 |
| `ERR_SUBSTITUTION_REQUEST_NOT_FOUND` | 404 |
| `ERR_RECALL_NOTICE_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_CHARGEBACK_CLAIM_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ORDER_NOT_DRAFT` | 409 |
| `ERR_ORDER_STATE_INVALID` | 409 |
| `ERR_ORDER_LINE_STATE_INVALID` | 409 |
| `ERR_CONTRACT_TRANSITION_INVALID` | 409 |
| `ERR_FORMULARY_STATE_INVALID` | 409 |
| `ERR_LOT_STATE_INVALID` | 409 |
| `ERR_SUBSTITUTION_STATE_INVALID` | 409 |
| `ERR_RECALL_STATE_INVALID` | 409 |
| `ERR_ROUTE_STATE_INVALID` | 409 |
| `ERR_CLAIM_STATE_INVALID` | 409 |
| `ERR_DUPLICATE_ROOM_CODE` | 409 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_DUPLICATE_CONTRACT_CODE` | 409 |
| `ERR_DUPLICATE_ROUTE_CODE` | 409 |
| `ERR_DUPLICATE_CONTRACT_LINE` | 409 |
| `ERR_DUPLICATE_FORMULARY_ITEM` | 409 |
| `ERR_CLAIM_ALREADY_OPEN` | 409 |
| `ERR_CONTROLLED_HANDLING_NOT_PERMITTED` | 422 |
| `ERR_COLD_CHAIN_ROOM_REQUIRED` | 422 |
| `ERR_LOT_NOT_ALLOCATABLE` | 422 |
| `ERR_LOT_EXPIRED` | 422 |
| `ERR_ITEM_NOT_ON_FORMULARY` | 422 |
| `ERR_NO_ACTIVE_CONTRACT_PRICE` | 422 |
| `ERR_CONTRACT_PERIOD_OVERLAP` | 409 |
| `ERR_ROOM_WINDOW_CONFLICT` | 409 |
| `ERR_STOP_OUTSIDE_ROOM_WINDOW` | 422 |
| `ERR_ROUTE_COLD_CAPACITY_EXCEEDED` | 409 |
| `ERR_CONTROLLED_QTY_LIMIT_EXCEEDED` | 422 |
| `ERR_SUBSTITUTION_ROUNDS_EXHAUSTED` | 409 |
| `ERR_NO_CHARGEBACK_ELIGIBLE_LINES` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
