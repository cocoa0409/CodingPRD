# Cookie Program API — Product Requirements Document

## 1. Introduction

Every cookie season, a council runs one of the largest youth-led retail operations in its region: forecasting demand, purchasing millions of packages from licensed bakers, allocating that supply across troops, staffing booth sales at host businesses, and — at the end — reconciling every cent of proceeds back to the troops that earned them. The work is unforgiving. Supply committed to troops must never exceed supply purchased from bakers; inventory moving between troops or out of a cupboard must be countersigned by two different hands; a booth slot at a popular grocery store must be shared fairly among dozens of competing troops; and a parent who signed a responsibility agreement for unsold packages cannot simply vanish at close-out.

This document specifies the Cookie Program API, mounted under the `/cookie-program` path prefix, which digitizes that entire operation. It covers season lifecycle management, the season product catalog, baker purchase orders and distribution-site receiving, troop initial and replenishment ordering under a forecast-attainment gate, double-acknowledgement inventory transfers, booth location and slot scheduling with both lottery and first-come allocation, the digital order channel with its independent payment and fulfillment tracks, participant responsibility agreements and troop financial accounts, allergen recalls, and the season close-out waterfall that forfeits uncollected balances, offsets proceeds against amounts owed, and donates unsold inventory. Two roles operate the system: council staff (`CouncilAdmin`) and troop leaders (`TroopLeader`), with strict segregation of duties wherever one actor could otherwise sign both sides of a transaction.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The declared roles are exactly two: `CouncilAdmin` and `TroopLeader`.

When `X-User-Role` is `CouncilAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`.

When `X-User-Role` is `TroopLeader`, `X-User-ID` is the `id` of the acting `Troop`; ownership checks on any resource that references a troop compare the resource's foreign-key field — `troop_id` on an order, account, digital order, booth request, or agreement, `source_troop_id` or `dest_troop_id` on a transfer — to `X-User-ID`. A troop leader who attempts to act on a resource owned by a different troop is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

Certain operations are reserved for `CouncilAdmin` alone: season lifecycle transitions, catalog and site administration, purchase-order management, order confirmation and rejection, transfer completion, booth slot creation, lottery draws and manual approvals, refunds, forfeitures and dispute resolution, recall activation, and the test clock. `TroopLeader` operations are scoped to the leader's own troop: drafting and submitting orders, requesting transfers and booths, signing transfer sides, running digital orders, and managing participant agreements. Deposit recording, transfer creation, and all read endpoints are shared.

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

All list endpoints accept two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, accepts a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0. List responses order results by `created_at` ascending, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties, Nested Retrieval, and Request Validation

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and a `version` integer. Timestamps are ISO 8601 UTC with three fractional digits. The `version` of a resource starts at 1 on creation and increments by one on every mutation of that resource. Requests with a missing required field, a value of the wrong type, or an unknown enum value are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Nested URLs validate their path identifiers left to right: the season first, then the resource within the season, then any deeper resource. The first identifier that fails to resolve — whether a season, order, line, site, purchase order, transfer, location, slot, request, digital order, agreement, recall, account, product, or troop — yields `ERR_NOT_FOUND` (HTTP 404) before any other check runs. A state transition attempted on a resource that is not in a state from which that transition exists is rejected with the domain-specific state error where one exists (`ERR_SEASON_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`, `ERR_TRANSFER_INVALID_STATE`, `ERR_REQUEST_INVALID_STATE`, `ERR_PAYMENT_INVALID_STATE`, `ERR_FULFILLMENT_INVALID_STATE`, `ERR_PO_INVALID_STATE`, `ERR_RECALL_INVALID_STATE`, `ERR_AGREEMENT_INVALID_STATE`), or with the generic `ERR_INVALID_STATE` (HTTP 409) where none applies.

### 2.5. The Season Ledger: Commitments, Purchases, and Remaining Supply

Each season maintains four computed counters that together form its supply ledger, and every allocation decision in the system reads from them. A resource's lifecycle position is always exposed through its `status` field, and season reads surface the ledger alongside it. `purchased_units` is the sum of `quantity` over the season's baker purchase orders whose status is `ORDERED`, `PARTIALLY_DELIVERED`, or `DELIVERED` — purchase orders still in `DRAFT` or already `CANCELLED` never count. `initial_commit_units` is the sum of `package_qty` across all lines of the season's orders in `CONFIRMED` or `FULFILLED` status. `pending_commit_units` is the same sum taken over orders in `SUBMITTED` status. `remaining_units` is `purchased_units` minus `initial_commit_units` minus `pending_commit_units`, and it is permitted to go negative when purchasing has not yet caught up with commitments. These counters recompute on every order submit, confirm, or reject and on every purchase-order placement or cancellation within the season.

### 2.6. Precision, Rounding, and Monetary Conventions

All money is integer cents. Unit counts are integer packages. The single percentage in the system, `forecast_attainment_pct`, is rounded half-up to two decimal places. Where an average unit price is needed — the donation price basis of a digital order, and the per-assignment valuation of participant packages — the average is rounded half-up to a whole cent exactly once, before any multiplication; the system never multiplies first and rounds the total. Blended per-unit proceeds in reporting are computed by summing exact per-line products first and rounding the final division half-up once at the end.

### 2.7. Optimistic Concurrency Control

Two writes are guarded by optimistic concurrency control, and only these two take a version field.

Creating a distribution site against a season requires the request to carry `expected_season_version`, equal to the season's current `version` as the client last observed it. If another writer has advanced the season's version since that read — an order confirmation or purchase-order placement legitimately recomputes the season ledger and bumps the version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from acting on a stale view of the season's capacity context.

Completing an inventory transfer requires `expected_transfer_version`, equal to the transfer's current `version`. If the transfer's version has advanced since the completing administrator last read it — for example a ship-signature retraction bumped the version and re-opened the signature state — the completion is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.8. Distribution Site Posture and Capacity Accounting

A distribution site's `posture` is computed, never set directly. It is `RECEIVING` when the owning season is `OPEN` or `SELLING` and the site's `received_units` is below its `capacity_units`; `FULL` once `received_units` reaches or exceeds `capacity_units`; `FROZEN` whenever the season is `RECONCILIATION`, `CLOSED`, or `CANCELLED`; and `DRAFT` while the season is still `DRAFT`. The `received_units` counter accumulates delivered packages across all purchase orders delivered to the site. The `hold_units` counter is the sum of `package_qty` over outbound transfers sourced from the site that are in `REQUESTED` or `SHIPPER_SIGNED` status. The readable `available_units` figure is `received_units` minus those outbound holds, minus the sum of `package_qty` over site-sourced transfers already in `RECEIVER_SIGNED` or `COMPLETED` status — a receiver signature already counts as shipped out — floored at zero for read purposes.

### 2.9. The Logical Clock

All time-gated behavior in the system reads a logical clock, never wall-clock time. At server startup the logical clock reads exactly 2026-09-01T00:00:00Z, and until it is explicitly set it continues to read that default. A `CouncilAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; each set re-evaluates the season's automatic opening-of-selling transition when the clock crosses `ordering_opens_at`.

### 2.10. Validation Pipeline Order

When several checks could reject the same request, they are evaluated in a fixed order so that the surfaced error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) runs first, then role authorization (`ERR_UNAUTHORIZED`), then left-to-right path existence (`ERR_NOT_FOUND`), then transition-state validity (the domain state errors above). Only after those four come the business rules, in this relative order: recall safety (`ERR_RECALLED_PRODUCT`) before referential ownership (`ERR_FORBIDDEN_OWNERSHIP`), before segregation of duties (`ERR_SOD_SAME_TROOP`), before booth conflicts (`ERR_BOOTH_CONFLICT`), before season and clock acceptance gates (`ERR_SEASON_NOT_ACCEPTING`), before the case-pack constraint (`ERR_CASE_PACK_VIOLATION`), before supply and capacity checks (`ERR_SUPPLY_INSUFFICIENT`), before fiscal guards (`ERR_FISCAL_VIOLATION`), and finally optimistic-concurrency staleness (`ERR_STALE_VERSION`) last. A caller fixing errors one at a time will therefore always meet them in this sequence.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Season: Catalog, Troops, Sites, and Purchasing

A `CouncilAdmin` begins a season by creating it with a human `code` that must be unique across all seasons (for example `COOKIE-2027`), a display `name`, and the ordering window `ordering_opens_at` and `ordering_closes_at`. The season is born in `DRAFT` status with its `version` at 1. Troops are registered independently with a unique `troop_number`, a `name`, and a `service_unit` grouping label, and begin life `ACTIVE` (a troop may later be `SUSPENDED` or `CLOSED`).

Before a season can open, its catalog must exist. Each product belongs to a season via its `season_id` and carries a `variety_code` unique within that season, a display `name`, a customer-facing `unit_price_cents` of at least 1, and a `troop_proceeds_cents` that must be strictly greater than zero and strictly less than `unit_price_cents` — a product whose proceeds would meet or exceed its price is rejected with `ERR_FISCAL_VIOLATION`. Products also carry `allergen_tags`, an array drawn from `PEANUT`, `TREE_NUT`, `MILK`, `EGG`, `WHEAT`, `SOY`, and `SESAME` that may be empty, and a `packages_per_case` defaulting to 12 and always at least 1, which drives the case-pack constraint everywhere packages move.

Distribution sites are created within a season with a `name`, a street `address`, and a `capacity_units` of at least 1, and this creation is one of the two optimistic-concurrency-guarded writes described in §2.7: the request must carry `expected_season_version`, and creating the site itself advances the season's `version` by one. Bulk purchasing is expressed as baker purchase orders, each naming a `baker_name` (the licensed baker identifier), a `product_id`, a `quantity` of at least 1, and a `delivery_site_id` designating the receiving site — a deliberate cross-aggregate reference from the purchasing stream into the distribution stream. A purchase order is created in `DRAFT`; placing it while the season is `DRAFT` or `OPEN` moves it to `ORDERED`, adds its `quantity` to the season's `purchased_units`, recomputes `remaining_units`, and bumps the season's `version`. A `DRAFT` purchase order may alternatively be cancelled outright.

Opening the season — the `DRAFT` → `OPEN` transition performed by a `CouncilAdmin` — requires at least one product in the catalog, failing with `ERR_PRODUCT_CATALOG_EMPTY` otherwise, and recomputes every site posture (sites with remaining capacity move from `DRAFT` to `RECEIVING`). A season still in `DRAFT` may instead be cancelled outright by a `CouncilAdmin`, which moves it to `CANCELLED` and freezes all of its sites.

Deliveries against a placed purchase order are recorded incrementally: each recording names a `delivered_now` package count and adds it to the order's cumulative `delivered_qty`, which starts at zero. Recording is permitted only from `ORDERED` or `PARTIALLY_DELIVERED`, and only while the receiving site's posture is `RECEIVING` with enough headroom — pushing `received_units` past `capacity_units` fails with `ERR_SITE_CAPACITY_EXCEEDED`. The cumulative total may never exceed the order's `quantity`; an over-shipment is refused with `ERR_OVERDELIVERY`. A recording that leaves `delivered_qty` short of `quantity` moves (or keeps) the order at `PARTIALLY_DELIVERED`; one that brings the cumulative total exactly to `quantity` completes it at `DELIVERED`. Every recording also adds `delivered_now` to the site's `received_units` and recomputes the site posture, flipping it to `FULL` at capacity.

### 3.2. Troop Ordering: Initial and Replenishment Orders

A `TroopLeader` drafts an order for their own troop by naming the `troop_id` and a `kind` of either `INITIAL` or `REPLENISHMENT`; the order is born `DRAFT`. Lines are added to a draft order one at a time, each recorded with its owning `order_id` and carrying a `product_id` and a `package_qty` that must be a positive multiple of that product's `packages_per_case` — requesting eleven packages of a twelve-per-case variety fails with `ERR_CASE_PACK_VIOLATION`. Each added line recomputes the order's `total_units`, the running sum of `package_qty` across its lines.

Submitting an order is gated five ways, and the gates surface in the pipeline order of §2.10. The order must be `DRAFT`, or `ERR_ORDER_INVALID_STATE` results; it must hold at least one line, or `ERR_ORDER_EMPTY` results; the acting leader must belong to the order's `troop_id`, or `ERR_FORBIDDEN_OWNERSHIP` results. The season must be accepting: an `INITIAL` order submits only while the season is `OPEN` or `SELLING`, while a `REPLENISHMENT` order submits only while the season is `SELLING`, with violations rejected as `ERR_SEASON_NOT_ACCEPTING`. Finally, an `INITIAL` order submits only while the logical clock is inside the ordering window — on or after `ordering_opens_at` and on or before `ordering_closes_at`, both boundaries inclusive — and a submission outside that window fails with `ERR_ORDER_WINDOW_CLOSED`. A successful submission moves the order to `SUBMITTED`, adds its `total_units` to the season's `pending_commit_units`, recomputes `remaining_units`, and advances the season's `version`.

Confirmation is the council's allocation decision. A `CouncilAdmin` confirming a `SUBMITTED` order first passes the recall gate — no `ACTIVE` recall whose `effective_at` is at or before the current instant may cover any product on the order's lines, else `ERR_RECALLED_PRODUCT` — and then the allocation gate: the season's `remaining_units` must be at least the order's `total_units`, else `ERR_SUPPLY_INSUFFICIENT`. Confirmation swaps the order's units out of `pending_commit_units` and into `initial_commit_units`, pins the order's `total_amount_cents` from the products' current prices at that moment, posts that amount as a charge against the troop account's `balance_cents`, and accrues per-package proceeds into the account's `proceeds_accrued_cents` — each line contributing its `package_qty` multiplied by the product's `troop_proceeds_cents`. Rejection instead moves the order to `REJECTED`, releases the pending commitment back into `remaining_units`, and records the supplied `reason` into the order's `rejection_reason`. Both confirmation and rejection advance the season's `version`. Fulfillment — `CONFIRMED` → `FULFILLED` — is permitted while the season is `OPEN` or `SELLING` and posts no further ledger change, since the charge was already booked at confirmation.

### 3.3. The Allocation Gate: Forecast Attainment and the Opening of Selling

The transition from `OPEN` to `SELLING` is not a human action; the system performs it automatically when two conditions coincide: the logical clock has reached `ordering_opens_at`, and `forecast_attainment_pct` has reached the selling gate. The attainment is one hundred times `initial_commit_units` divided by `purchased_units`, rounded half-up to two decimal places — committed demand as a percentage of purchased supply. When `purchased_units` is zero the attainment is null and the gate never opens. The gate itself is inclusive: an attainment of at least 80.00 percent opens selling. An attainment above 120.00 percent signals over-commitment and surfaces as an advisory flag on season reads; it does not block anything.

Season summary reads additionally expose a provisional attainment that counts both confirmed and pending commitments in the numerator — useful while orders are still `SUBMITTED` — but this provisional figure is never used for the selling gate; the gate and all post-selling reporting use the confirmed-only final attainment, which for identical data is always the lower of the two whenever pending orders exist. Once the season is `SELLING`, the booth lottery becomes drawable, first-come booth requests become acceptable, replenishment orders open up, and digital-order payments can be recorded.

### 3.4. Inventory Transfers and Cupboard Accountability

Transfers move inventory, never money. A transfer is created naming the `season_id`, `product_id`, and a `package_qty` that obeys the same case-pack constraint as order lines, and it comes in three shapes: troop-to-troop, with both `source_troop_id` and `dest_troop_id` set; cupboard-to-troop, with `source_troop_id` null and `site_id` set; or troop-to-cupboard return, with `dest_troop_id` null and `site_id` set. The `site_id` is required exactly when either troop side is null, and null otherwise. A transfer may also carry a `counter_transfer_id` linking it to a sibling transfer in an even swap. Creation lands the transfer in `REQUESTED`.

The ship side signs first. Signing the ship side of a `REQUESTED` transfer requires the acting troop to be the source troop — or a `CouncilAdmin` when the source is a cupboard — and, when the request was created by a troop, the signing troop must differ from the requesting troop; the same troop signing its own request fails with `ERR_SOD_SAME_TROOP`. An optional `signing_troop_id` in the request body records which troop the signer represents. For a site-sourced transfer, the site's `available_units` must be at least the `package_qty`, else `ERR_SUPPLY_INSUFFICIENT`, and a successful signature records the signer in `shipper_signed_by_troop_id` and places a hold by adding the quantity to the site's `hold_units`. The receive side then signs: the acting troop must be the destination troop (or a `CouncilAdmin` for a cupboard destination) and must differ from the troop recorded in `shipper_signed_by_troop_id` — again `ERR_SOD_SAME_TROOP` on violation — whereupon `receiver_signed_by_troop_id` is recorded and the transfer reaches `RECEIVER_SIGNED`. Either signature step advances the transfer's `version` by one.

Completion is a `CouncilAdmin` act guarded by optimism and safety: the request carries `expected_transfer_version` and is rejected with `ERR_STALE_VERSION` when the transfer has moved on, and any `ACTIVE` recall covering the transfer's product with `effective_at` at or before now rejects with `ERR_RECALLED_PRODUCT`. On completion of a site-sourced transfer the hold is released and the outbound shipment is recorded, decreasing `available_units`; on completion of a troop-to-cupboard return the site's `received_units` is unchanged but `available_units` increases by the returned quantity. Both troop accounts receive a memo note only — no balance moves. When a completed transfer has a `counter_transfer_id` whose counter-transfer is itself sitting at `RECEIVER_SIGNED`, the counter-transfer auto-completes in the same breath, preserving swap symmetry.

Two escape hatches exist before completion. While a transfer is `REQUESTED`, either the source or the destination troop may decline it — `REQUESTED` → `DECLINED` — or the requesting troop may cancel it outright. And a ship signature can be retracted by the same troop that gave it, returning the transfer from `SHIPPER_SIGNED` to `REQUESTED`, clearing `shipper_signed_by_troop_id` to null, releasing any site hold, and advancing the transfer's `version` — which is precisely the interleaving the completion-time version guard exists to catch.

### 3.5. Booth Locations, Slots, and the Lottery

Booth selling begins with the host. A `CouncilAdmin` registers a booth location with the `host_business_name`, an `address`, the boolean `host_permission_granted` — false by default and true only when the host business has granted written permission — and an optional `blackout_dates` array of ISO dates on which no selling may occur. Slots are then created at a location — the new slot's `location_id` binding it to its host — with a `start_at` and an `end_at` that must fall strictly after the start, forming a half-open interval, plus a `capacity_troops` defaulting to 1. Slot creation is refused with `ERR_BOOTH_CONFLICT` when host permission is missing, when the slot's date appears in the location's blackout dates, or when the new interval overlaps an existing slot at the same location — touching boundaries, where one slot's `end_at` equals another's `start_at`, are explicitly allowed.

Troops request slots in one of two `mode`s, and each request is recorded with the `slot_id` it targets and the requesting `troop_id`. A `FIRST_COME` request needs no rank and is auto-approved on submission when the season is `SELLING` and capacity remains. A `LOTTERY` request carries a `lottery_rank` of at least 1 expressing preference; a rank greater than 2 makes the request ineligible at draw time. In both modes a troop may hold at most one `PENDING` or `APPROVED` request per slot, with duplicates refused as `ERR_BOOTH_CONFLICT`.

Manual approval of a `PENDING` first-come request is a `CouncilAdmin` act with four gates, evaluated in the pipeline order of §2.10: the request must be `PENDING` (`ERR_REQUEST_INVALID_STATE`), the season must be `SELLING` (`ERR_SEASON_NOT_SELLING`), the location's `host_permission_granted` must be true (`ERR_HOST_PERMISSION_MISSING`), and the count of approved requests on the slot must still be below `capacity_troops` (`ERR_BOOTH_CAPACITY_FULL`). Approval increments the slot's occupancy. Only a `CouncilAdmin` may approve; segregation between the approving role and the requesting troop is enforced structurally by that role separation, and the decision is recorded in the request's `decision_reason` (for approvals and denials alike — values such as `CAPACITY_FULL`, `RANK_GT_2`, or `SEASON_NOT_SELLING`).

The lottery draw resolves a slot's pending lottery requests in one sweep. Candidates are the slot's `PENDING` requests in `LOTTERY` mode whose `lottery_rank` is at most 2, ordered by rank ascending and then by `created_at` ascending — earliest submission breaks ties, and the request `id` is never used as an ordering key. The draw approves the first candidates up to the slot's remaining capacity (its `capacity_troops` minus the current approved count) and denies the rest with `decision_reason` set to `LOTTERY_LOST`; pending lottery requests whose rank exceeds 2 are denied at the same draw with `decision_reason` set to `RANK_GT_2`. The draw response lists the `approved_request_ids` and the `denied_request_ids`. A requesting troop may cancel its own request while `PENDING`, and may also cancel after approval — which frees one unit of slot occupancy — but a leader cancelling another troop's request is refused with `ERR_FORBIDDEN_OWNERSHIP`.

### 3.6. Digital Orders: Payment and Fulfillment as Parallel Tracks

A digital order pairs a customer-facing purchase with a fulfilling troop, created by a `TroopLeader` with the `troop_id`, a `customer_email`, a `fulfillment_type` of `SHIPPED` or `IN_PERSON`, an `items` array of product and quantity pairs — each quantity at least 1 and each product belonging to the same season — and an optional `donation_units` count, defaulting to zero, representing packages donated through the order that are not drawn from troop inventory. The order's two status dimensions then evolve independently: `payment_status` walks `PENDING`, `PAID`, `UNCOLLECTED`, and `REFUNDED`, while `fulfillment_status` walks `OPEN`, `DELIVERED`, and `CANCELLED`; the order is fully terminal only when payment is `REFUNDED` and fulfillment is `CANCELLED`.

The order's `total_amount_cents` is computed once and pinned at creation. The item portion is the sum of each item's `package_qty` multiplied by its product's current `unit_price_cents`. The donation portion prices each donated package at the season's average unit price: the sum of `unit_price_cents` over all of the season's products, divided by the product count, rounded half-up to a whole cent, and only then multiplied by `donation_units`. The order of operations is pinned — average, then round, then multiply — and a product under recall still participates in the average basis.

Recording payment requires the season to be `SELLING` (else `ERR_SEASON_NOT_SELLING`) and the payment to be `PENDING` (else `ERR_PAYMENT_INVALID_STATE`); it moves payment to `PAID`, charges the full `total_amount_cents` to the troop account's `balance_cents` as customer remittance, and accrues the items' per-package proceeds into `proceeds_accrued_cents`. An `IN_PERSON` order whose customer never pays can instead be marked `UNCOLLECTED`; attempting that on a `SHIPPED` order fails with `ERR_FULFILLMENT_TYPE_MISMATCH`, since shipped orders cannot be uncollected. When the marking supplies an optional `agreement_id` linking the order to a participant agreement, that agreement's `outstanding_cents` grows by the order total — and if the agreement was already `PAID` it stays `PAID`; the linkage moves money, not status.

Delivery requires the payment to be `PAID` — delivering an unpaid order fails with `ERR_UNPAID_DELIVERY` — and passes the recall gate for every product in the order (`ERR_RECALLED_PRODUCT`). Refunding is a `CouncilAdmin` act requiring payment `PAID` and fulfillment anything other than `DELIVERED`; refunding after delivery is refused with `ERR_ALREADY_DELIVERED`. The refund credits `total_amount_cents` back off the troop account's `balance_cents` and claws the accrued proceeds back out of `proceeds_accrued_cents`. Cancelling fulfillment is allowed from `OPEN`, but cancelling an order whose payment is already `PAID` requires the refund to have been processed first, else `ERR_REFUND_REQUIRED`. Each of these payment and fulfillment mutations advances the digital order's `version` by one.

### 3.7. Participant Agreements, Deposits, and Financial Accountability

Each troop has exactly one account per season — the pair of `troop_id` and `season_id` is unique — opened by a `CouncilAdmin` with a `balance_cents` of zero. The account's `balance_cents` is a signed ledger of what the troop owes the council: charges for confirmed orders, forfeitures, and recall chargebacks, net of credits from deposits, refunds, and proceeds offsets. The `proceeds_accrued_cents` counter accumulates per-package proceeds over confirmed and fulfilled order lines plus settled digital-order items. The `uncollected_amount_cents` counter is the sum of `outstanding_cents` over the troop's agreements in `PENDING` or `DISPUTED` status for the season, recomputed on every agreement mutation. The `deposit_cents` counter sums confirmed deposit credits.

Deposits are recorded against an account by either role with an `amount_cents` and a `reference`; each deposit adds to `deposit_cents`, subtracts from `balance_cents`, and advances the account's `version`.

Participant agreements bind an individual seller's family to financial responsibility. A `TroopLeader` creates one with the `season_id`, the `participant_name`, the `parent_name` accepting responsibility, and the `signed_responsibility` flag — which must be true before packages can be assigned — plus an optional `assigned_packages` and `paid_amount_cents`, both defaulting to zero and never negative. The agreement's `outstanding_cents` is the assigned packages valued at the season-average unit price — the average rounded half-up to a whole cent per assignment — minus `paid_amount_cents`, floored at zero. Each agreement also carries a computed `incentive_tier` driven by inclusive package thresholds: `GOLD` at one hundred or more assigned packages, `SILVER` at fifty or more, `BRONZE` at twenty or more, and `NONE` below that — exactly twenty packages earns `BRONZE`, while nineteen earns nothing. The tier recomputes on creation, on update, and at settlement.

Settling an agreement — from `PENDING` or `DISPUTED` — requires the supplied `settle_amount_cents` to cover the outstanding balance in full after the settle; partial payment is rejected with `ERR_UNDERPAID`. A successful settle moves the agreement to `PAID`, credits the settled amount off the troop account's `balance_cents`, recomputes `uncollected_amount_cents`, and refreshes the reported `incentive_tier`. A leader may instead dispute a `PENDING` agreement with a `reason`, which leaves the amount counted as uncollected; a `CouncilAdmin` resolves a dispute, returning the agreement from `DISPUTED` to `PENDING`. Forfeiture is the hard end: a `CouncilAdmin` may forfeit an agreement in `PENDING` or `DISPUTED`, posting the full `outstanding_cents` at that moment as a charge against the troop account — parent responsibility is enforced at troop level — and dropping the agreement out of the uncollected total.

### 3.8. Recalls and Product Safety

When a mislabelled allergen or a quality issue surfaces, a `CouncilAdmin` creates a recall notice in `DRAFT` naming the `product_id`, a free-text `reason`, and an `effective_at` instant that must not precede the season's own creation. Activation — permitted only while the season is `OPEN` or `SELLING`, else `ERR_SEASON_INVALID_STATE` — moves the notice to `ACTIVE`, and from its `effective_at` forward the recall blocks three operations for that product: order confirmation, transfer completion, and digital-order delivery, each failing with `ERR_RECALLED_PRODUCT`. Activation also cascades one level deeper: every `SUBMITTED` order containing the recalled product is flagged with `review_required` on subsequent reads, so council staff can see exposure before confirming. The recall quarantines stock logically; the season's `remaining_units` is deliberately unchanged. Lifting an `ACTIVE` recall releases all three gates. A recall still sitting in `DRAFT` is itself a close-out blocker, as §3.9 describes.

### 3.9. Reconciliation and Season Close-Out

When selling winds down, a `CouncilAdmin` moves the season from `SELLING` to `RECONCILIATION`. The move is refused with `ERR_TRANSFER_IN_FLIGHT` while any transfer of the season sits in `REQUESTED`, `SHIPPER_SIGNED`, or `RECEIVER_SIGNED` — inventory in motion must land first — and with `ERR_BOOTH_REQUEST_PENDING` while any booth request remains `PENDING`. On success every site posture flips to `FROZEN`; already-`APPROVED` booth requests remain queryable but no new ones are accepted, and the season's `version` advances.

Close-out, the `RECONCILIATION` → `CLOSED` transition, runs the season's financial endgame and is guarded twice: every troop account's `uncollected_amount_cents` must be zero or all of its `PENDING` agreements must already be `FORFEITED`, else `ERR_UNRESOLVED_UNCOLLECTED`; and no recall notice may remain in `DRAFT`, else `ERR_RECALL_DRAFT_OPEN`. The settlement then runs in a pinned order. First, the forfeiture sweep: every agreement still `PENDING` or `DISPUTED` is moved to `FORFEITED` and its `outstanding_cents` posted as a charge against its troop's account. Second — only after those charges have landed — the proceeds waterfall: for each troop account, the offset is the lesser of the account's `proceeds_accrued_cents` and the positive part of its `balance_cents`; the offset is subtracted from `balance_cents`, and whatever proceeds remain beyond the offset become the `proceeds_payable_cents` owed back to the troop. Swapping this order would change balances whenever proceeds fall short of charges, which is why forfeiture always posts first. Third, the unsold-inventory sweep: for each product, the units purchased but neither committed to orders nor fulfilled digitally are donated, producing bulk donation entries per site that are surfaced through the close-out response alongside the settlement summary — `settled_accounts`, `total_proceeds_offset_cents`, `donated_unsold_units`, and `forfeited_agreements`. The season's `version` advances one final time.

Separately from close-out, a per-unit proceeds reporting capability exposes `blended_proceeds_cents` for a troop within a season: the sum of exact per-line proceeds products — each line's `package_qty` times its product's `troop_proceeds_cents` — over the troop's `CONFIRMED` and `FULFILLED` order lines, divided by the total packages across those lines, with the single division rounded half-up at the end.

## 4. Endpoint Definitions

All endpoints live under the `/cookie-program` prefix. Creating a new resource returns HTTP 201; every successful modification, action, or read returns HTTP 200. Path parameters such as `{seasonId}`, `{orderId}`, `{lineId}`, `{siteId}`, `{poId}`, `{transferId}`, `{locationId}`, `{slotId}`, `{requestId}`, `{agreementId}`, `{recallId}`, `{accountId}`, `{troopId}`, and `{productId}` resolve to the `id` of the corresponding resource and are validated left to right per §2.4. Request payloads, gates, and side effects are specified in §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /cookie-program/seasons | Create a CookieSeason in DRAFT | CouncilAdmin |
| GET | /cookie-program/seasons | List seasons (paginated, filterable by status) | CouncilAdmin, TroopLeader |
| GET | /cookie-program/seasons/{seasonId} | Get one season including computed commitment and attainment fields | CouncilAdmin, TroopLeader |
| POST | /cookie-program/seasons/{seasonId}/open | DRAFT → OPEN | CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/begin-reconciliation | SELLING → RECONCILIATION (guarded: no in-flight transfers, no pending booth requests) | CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/close-out | RECONCILIATION → CLOSED; forfeiture sweep, proceeds waterfall, unsold donation sweep; returns settlement summary | CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/products | Create a CookieProduct in the season catalog | CouncilAdmin |
| GET | /cookie-program/seasons/{seasonId}/products | List products of a season | CouncilAdmin, TroopLeader |
| POST | /cookie-program/troops | Register a troop (ACTIVE) | CouncilAdmin |
| GET | /cookie-program/troops/{troopId} | Get a troop | CouncilAdmin, TroopLeader |
| POST | /cookie-program/seasons/{seasonId}/accounts | Open a TroopAccount for a troop in the season | CouncilAdmin |
| GET | /cookie-program/seasons/{seasonId}/accounts | List accounts of a season, filterable by troop | CouncilAdmin, TroopLeader |
| POST | /cookie-program/accounts/{accountId}/deposits | Record a troop deposit (credit) against the account | TroopLeader, CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/orders | Create a DRAFT CookieOrder for a troop | TroopLeader |
| GET | /cookie-program/seasons/{seasonId}/orders | List orders of a season, filterable by troop and status | CouncilAdmin, TroopLeader |
| POST | /cookie-program/seasons/{seasonId}/orders/{orderId}/lines | Add a line to a DRAFT order (case-pack enforced) | TroopLeader |
| GET | /cookie-program/orders/{orderId}/lines | List lines of an order | CouncilAdmin, TroopLeader |
| POST | /cookie-program/seasons/{seasonId}/orders/{orderId}/submit | DRAFT → SUBMITTED (window and ownership gates) | TroopLeader |
| POST | /cookie-program/seasons/{seasonId}/orders/{orderId}/confirm | SUBMITTED → CONFIRMED (recall and allocation gates; posts charge and proceeds) | CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/orders/{orderId}/reject | SUBMITTED → REJECTED | CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/orders/{orderId}/fulfill | CONFIRMED → FULFILLED | CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/sites | Create a DistributionSite (OCC-guarded on season version) | CouncilAdmin |
| GET | /cookie-program/seasons/{seasonId}/sites | List sites of a season | CouncilAdmin, TroopLeader |
| POST | /cookie-program/seasons/{seasonId}/baker-pos | Create a DRAFT BakerPurchaseOrder | CouncilAdmin |
| GET | /cookie-program/seasons/{seasonId}/baker-pos | List purchase orders of a season, filterable by delivery site | CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/baker-pos/{poId}/place | DRAFT → ORDERED (adds to purchased supply) | CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/baker-pos/{poId}/record-delivery | Record a partial or full delivery to a site (capacity and posture gates) | CouncilAdmin |
| POST | /cookie-program/transfers | Create a REQUESTED InventoryTransfer (troop-to-troop, cupboard-to-troop, or troop-to-cupboard) | TroopLeader, CouncilAdmin |
| GET | /cookie-program/transfers | List transfers, filterable by season, source troop, destination troop, site, product, signers, counter-transfer, and status | CouncilAdmin, TroopLeader |
| POST | /cookie-program/transfers/{transferId}/sign-ship | REQUESTED → SHIPPER_SIGNED (segregation and availability gates; places site hold when site-sourced) | TroopLeader, CouncilAdmin |
| POST | /cookie-program/transfers/{transferId}/sign-receive | SHIPPER_SIGNED → RECEIVER_SIGNED (segregation versus ship signer) | TroopLeader, CouncilAdmin |
| POST | /cookie-program/transfers/{transferId}/complete | RECEIVER_SIGNED → COMPLETED (OCC on transfer version; recall gate; swap symmetry) | CouncilAdmin |
| POST | /cookie-program/transfers/{transferId}/retract-ship-signature | SHIPPER_SIGNED → REQUESTED (releases site hold) | TroopLeader |
| POST | /cookie-program/transfers/{transferId}/decline | REQUESTED → DECLINED | TroopLeader, CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/booth-locations | Create a BoothLocation with host permission flag | CouncilAdmin |
| GET | /cookie-program/seasons/{seasonId}/booth-locations | List booth locations of a season | CouncilAdmin, TroopLeader |
| POST | /cookie-program/booth-slots | Create a BoothSlot at a location (permission, blackout, and half-open overlap checks) | CouncilAdmin |
| GET | /cookie-program/booth-locations/{locationId}/slots | List slots of a location | CouncilAdmin, TroopLeader |
| POST | /cookie-program/booth-slots/{slotId}/requests | Create a BoothRequest (LOTTERY with rank, or FIRST_COME) | TroopLeader |
| GET | /cookie-program/booth-slots/{slotId}/requests | List requests of a slot, filterable by status | CouncilAdmin, TroopLeader |
| POST | /cookie-program/booth-slots/{slotId}/draw-lottery | Run the lottery draw: approve by rank then earliest submission up to capacity; deny the rest | CouncilAdmin |
| POST | /cookie-program/booth-requests/{requestId}/approve | Manually approve a PENDING first-come request (SELLING, capacity, and permission gates) | CouncilAdmin |
| POST | /cookie-program/booth-requests/{requestId}/cancel | PENDING or APPROVED → CANCELLED by the owning troop (frees capacity when approved) | TroopLeader |
| POST | /cookie-program/seasons/{seasonId}/digital-orders | Create a DigitalOrder (SHIPPED or IN_PERSON; donation units allowed; total pinned at creation) | TroopLeader |
| GET | /cookie-program/digital-orders/{orderId} | Get a digital order | CouncilAdmin, TroopLeader |
| POST | /cookie-program/digital-orders/{orderId}/record-payment | Payment PENDING → PAID (SELLING gate; posts charge and proceeds) | TroopLeader |
| POST | /cookie-program/digital-orders/{orderId}/mark-uncollected | Payment PENDING → UNCOLLECTED (IN_PERSON only; links to an agreement when provided) | TroopLeader |
| POST | /cookie-program/digital-orders/{orderId}/mark-delivered | Fulfillment OPEN → DELIVERED (requires PAID; recall gate) | TroopLeader |
| POST | /cookie-program/digital-orders/{orderId}/refund | Payment PAID → REFUNDED (requires not DELIVERED; credits account, claws back proceeds) | CouncilAdmin |
| POST | /cookie-program/troops/{troopId}/agreements | Create a ParticipantAgreement (parent responsibility) | TroopLeader |
| GET | /cookie-program/troops/{troopId}/agreements | List agreements of a troop, filterable by season and status | CouncilAdmin, TroopLeader |
| POST | /cookie-program/agreements/{agreementId}/settle | PENDING or DISPUTED → PAID when the settle covers the full outstanding | TroopLeader |
| POST | /cookie-program/agreements/{agreementId}/dispute | PENDING → DISPUTED | TroopLeader |
| POST | /cookie-program/agreements/{agreementId}/forfeit | PENDING or DISPUTED → FORFEITED (charge posted to the troop account) | CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/recalls | Create a DRAFT RecallNotice for a product | CouncilAdmin |
| GET | /cookie-program/seasons/{seasonId}/recalls | List recalls of a season, filterable by product and status | CouncilAdmin, TroopLeader |
| POST | /cookie-program/seasons/{seasonId}/recalls/{recallId}/activate | DRAFT → ACTIVE (blocks confirm, complete, deliver) | CouncilAdmin |
| POST | /cookie-program/seasons/{seasonId}/recalls/{recallId}/lift | ACTIVE → LIFTED | CouncilAdmin |
| POST | /cookie-program/_clock/set_current_utc | Set the logical clock (startup default 2026-09-01T00:00:00Z; re-evaluates the OPEN → SELLING auto-transition) | CouncilAdmin |
| GET | /cookie-program/products/{productId} | Get one CookieProduct | CouncilAdmin, TroopLeader |
| GET | /cookie-program/products | List products globally, filterable by season | CouncilAdmin, TroopLeader |
| GET | /cookie-program/accounts | List TroopAccounts, filterable by troop and season | CouncilAdmin, TroopLeader |
| GET | /cookie-program/accounts/{accountId} | Get one TroopAccount | CouncilAdmin, TroopLeader |
| GET | /cookie-program/orders/{orderId} | Get one CookieOrder | CouncilAdmin, TroopLeader |
| GET | /cookie-program/orders | List CookieOrders, filterable by season, troop, and status | CouncilAdmin, TroopLeader |
| GET | /cookie-program/order-lines/{lineId} | Get one CookieOrderLine | CouncilAdmin, TroopLeader |
| GET | /cookie-program/order-lines | List CookieOrderLines, filterable by order and product | CouncilAdmin, TroopLeader |
| GET | /cookie-program/baker-pos/{poId} | Get one BakerPurchaseOrder | CouncilAdmin |
| GET | /cookie-program/baker-pos | List BakerPurchaseOrders, filterable by season, product, and delivery site | CouncilAdmin |
| GET | /cookie-program/sites/{siteId} | Get one DistributionSite | CouncilAdmin, TroopLeader |
| GET | /cookie-program/sites | List DistributionSites, filterable by season | CouncilAdmin, TroopLeader |
| GET | /cookie-program/transfers/{transferId} | Get one InventoryTransfer | CouncilAdmin, TroopLeader |
| GET | /cookie-program/booth-locations/{locationId} | Get one BoothLocation | CouncilAdmin, TroopLeader |
| GET | /cookie-program/booth-locations | List BoothLocations, filterable by season | CouncilAdmin, TroopLeader |
| GET | /cookie-program/booth-slots/{slotId} | Get one BoothSlot | CouncilAdmin, TroopLeader |
| GET | /cookie-program/booth-slots | List BoothSlots, filterable by location | CouncilAdmin, TroopLeader |
| GET | /cookie-program/booth-requests/{requestId} | Get one BoothRequest | CouncilAdmin, TroopLeader |
| GET | /cookie-program/booth-requests | List BoothRequests, filterable by slot, troop, and status | CouncilAdmin, TroopLeader |
| GET | /cookie-program/digital-orders | List DigitalOrders, filterable by season, troop, and payment status | CouncilAdmin, TroopLeader |
| GET | /cookie-program/agreements/{agreementId} | Get one ParticipantAgreement | CouncilAdmin, TroopLeader |
| GET | /cookie-program/agreements | List ParticipantAgreements, filterable by troop, season, and status | CouncilAdmin, TroopLeader |
| GET | /cookie-program/recalls/{recallId} | Get one RecallNotice | CouncilAdmin, TroopLeader |
| GET | /cookie-program/recalls | List RecallNotices, filterable by season, product, and status | CouncilAdmin, TroopLeader |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this table is the identifier-to-status reference only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_SEASON_INVALID_STATE | 409 |
| ERR_PRODUCT_CATALOG_EMPTY | 422 |
| ERR_ORDER_INVALID_STATE | 409 |
| ERR_ORDER_EMPTY | 422 |
| ERR_ORDER_WINDOW_CLOSED | 422 |
| ERR_SEASON_NOT_ACCEPTING | 422 |
| ERR_SUPPLY_INSUFFICIENT | 422 |
| ERR_CASE_PACK_VIOLATION | 422 |
| ERR_TRANSFER_INVALID_STATE | 409 |
| ERR_TRANSFER_IN_FLIGHT | 409 |
| ERR_SOD_SAME_TROOP | 422 |
| ERR_REQUEST_INVALID_STATE | 409 |
| ERR_BOOTH_REQUEST_PENDING | 409 |
| ERR_BOOTH_CONFLICT | 409 |
| ERR_BOOTH_CAPACITY_FULL | 422 |
| ERR_HOST_PERMISSION_MISSING | 422 |
| ERR_SEASON_NOT_SELLING | 422 |
| ERR_PAYMENT_INVALID_STATE | 409 |
| ERR_FULFILLMENT_INVALID_STATE | 409 |
| ERR_FULFILLMENT_TYPE_MISMATCH | 422 |
| ERR_UNPAID_DELIVERY | 422 |
| ERR_REFUND_REQUIRED | 422 |
| ERR_ALREADY_DELIVERED | 422 |
| ERR_PO_INVALID_STATE | 409 |
| ERR_OVERDELIVERY | 422 |
| ERR_SITE_CAPACITY_EXCEEDED | 422 |
| ERR_RECALL_INVALID_STATE | 409 |
| ERR_RECALL_DRAFT_OPEN | 409 |
| ERR_RECALLED_PRODUCT | 422 |
| ERR_AGREEMENT_INVALID_STATE | 409 |
| ERR_UNDERPAID | 422 |
| ERR_UNRESOLVED_UNCOLLECTED | 409 |
| ERR_FISCAL_VIOLATION | 422 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_STALE_VERSION | 412 |
