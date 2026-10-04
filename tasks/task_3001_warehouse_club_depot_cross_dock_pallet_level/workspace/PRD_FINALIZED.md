# Warehouse Club Cross-Dock & Pallet-Level Replenishment API — Product Requirements Document

## 1. Introduction

Warehouse club retail lives and dies by the pallet. A club has no backroom of consequence: every unit of merchandise either sits on a sales-floor pallet slot or it does not exist for the member. This document specifies the API that coordinates the depot-to-club pipeline for a warehouse club operator — the system that decides how many selling units ride on a pallet, when a vendor truck may dock, how inbound pallets are re-allocated to clubs on the same day they arrive, and what happens to treasure-hunt one-time-buy items once their window closes.

The system serves several operating constituencies whose interests collide daily. Regional operations administrators define the map of regions, vendors, and clubs. Category managers design item pallet quantities under hard physical constraints — case pack, pallet footprint, and the 48-by-40-inch standard floor slot — and shepherd treasure-hunt items through sell-through-or-markdown decisions with a strict no-reorder rule. Depot managers run the receiving dock: booking compliance, unload fees, chargebacks for late or over-count deliveries. Depot planners execute same-day cross-dock runs that reallocate received pallets to clubs whose demographics and recent velocity promise the best sell-through, without ever overflowing a club's floor slots. Membership desk staff register members, record purchases under per-membership caps, handle complaints that feed deletion reviews, and ring up ancillary sales in the gas, pharmacy, and optical departments that share the club's membership base.

Because every decision in this pipeline is dated — deliveries arrive on a date, runs cut off at a time of day, chargebacks age in 30-day buckets, complaint windows trail 30 days — the server maintains a logical clock that actors may advance through a dedicated capability. All temporal rules in this document refer to that logical clock, never to wall-clock time. The remainder of this document defines the global contracts (§2), the business workflows (§3), the endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the acting role. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint — or whose entity-backed identity does not match the resource being acted upon — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles, spelled exactly as clients must send them, are `RegionalOps`, `CategoryManager`, `DepotManager`, `DepotPlanner`, `MembershipDesk`, and `VendorRep`.

Role identities bind to resources as follows. When `X-User-Role` is `VendorRep`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a vendor — most importantly appointment booking, appointment cancellation, and chargeback appeal — compare the resource's `vendor_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is any of `RegionalOps`, `CategoryManager`, `DepotManager`, `DepotPlanner`, or `MembershipDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`.

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

All list endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`. The default sort order for every list endpoint is `created_at` ascending; no tie-break on `id` is ever applied for business purposes.

### 2.4. Common Resource Properties

Every persisted entity carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC format with three fractional digits, an `updated_at` timestamp of the same format, and a `version` integer that starts at 1 and increments by exactly 1 on every mutation of that entity. Clients must treat `updated_at` as refreshed and `version` as advanced whenever any write — direct or cascading — touches a resource. Several workflows in §3 mutate a parent entity's `version` as a side effect of writing a child (for example, proposing an allocation advances the parent run's version); readers must assume `version` is the single ordering witness for any aggregate.

### 2.5. The Logical Clock and Time-Driven System Transitions

The server keeps a logical clock, expressed as an ISO 8601 UTC instant. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`; before any operator sets it, every temporal rule in this document is evaluated against that default, and the server never falls back to wall-clock time. A `RegionalOps` administrator may advance the logical clock by submitting a `to_iso8601` instant; the clock must never move backwards, and a request attempting to do so is rejected. The capability returns the new `current_utc` together with a `triggered_transitions` count.

Advancing the clock fires the due system auto-transitions in a single pass: any appointment still `BOOKED` whose `delivery_date` end-of-day has passed becomes `NO_SHOW` with an accompanying chargeback; any pallet still `RECEIVED` whose `received_date` is earlier than the current logical date becomes `STRANDED`; and any chargeback still `ASSESSED` whose `assessed_at` date is more than seven days in the past auto-confirms to `CONFIRMED`, with the vendor-total and compliance-score consequences described in §3.6.

### 2.6. Numeric Precision and Rounding

Monetary amounts are integers of cents. Whenever a fee, chargeback, or other money figure is computed from a non-integer intermediate, the result is rounded half-up to whole cents. The allocation priority score is rounded half-up to four decimal places while its intermediate factors remain unrounded. The complaint weighted score is rounded half-up to two decimal places. Sell-through percentage is an integer percent rounded half-up. Pallet footprints are compared at two decimal places. Compliance scores are integer basis points.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control against stale parent versions.

When proposing an allocation into a cross-dock run (identified by the `run_id` path parameter), the request must carry `expected_cross_dock_run_version` holding the client-observed `version` of the parent run. If the run's current `version` differs — because another writer has since added an allocation, voided one, or committed the run — the request is rejected with `ERR_STALE_RUN_VERSION` (HTTP 412), since the client's view of remaining club capacity is stale.

When recording a markdown decision on an item, the request must carry `expected_item_version` holding the client-observed `version` of the item. If the item's `version` has advanced since that read, the request is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412), forcing the deciding manager to re-read the item before deciding.

Endpoints not named above accept no version field.

### 2.8. Nested Resources and Reference Validation

Nested URLs are validated left to right: each path parameter must resolve to an existing resource before any deeper segment or body reference is considered, and a dangling reference — path or body — is rejected with `ERR_NOT_FOUND` (HTTP 404). Body references are validated after the path resolves. Requests with a malformed body or a missing required field are rejected with `ERR_INVALID_REQUEST` (HTTP 400), and requests whose field values violate format, range, or enum rules — a `sku` that is not exactly seven digits, a region `code` that is not two to four uppercase letters, a time not in HH:MM form — are rejected with `ERR_VALIDATION` (HTTP 400).

### 2.9. Validation Priority Order

When several validations could reject the same request, they are evaluated in a fixed order so the surfaced error is deterministic: authentication first (`ERR_UNAUTHENTICATED`), then authorization (`ERR_FORBIDDEN`), then body well-formedness (`ERR_INVALID_REQUEST`), then field-level format and range checks (`ERR_VALIDATION`), then reference existence (`ERR_NOT_FOUND`), then state-machine admissibility (`ERR_INVALID_STATE`), and only then the business gates — safety gates, department enablement, frozen-club posture, appointment-window conflicts, cutoff timing, uniqueness and consistency constraints, same-day cross-dock, member caps, club capacity, markdown rules, active-reference checks, and referential guards, in the order those gates appear in §3. When an endpoint's §3 narrative pins a more specific order among business gates — as the allocation proposal does in §3.3, where the safety gates, including the CONSTRAINED approval gate, precede club capacity — that narrative order governs. A request that would fail two business checks surfaces the earlier one in this ordering.

## 3. Business Logic & Workflows

### 3.1. Merchandise Setup: Regions, Vendors, Clubs, Depots, and Item Pallet Design

A `RegionalOps` administrator opens the world by registering regions. A region carries a human-readable `name`, a `code` matching the regular expression `^[A-Z]{2,4}$` — two to four uppercase ASCII letters — that must be unique across regions, and `avg_member_income_cents`, the average member household income in cents that later feeds allocation weighting; the income figure must be at least zero.

Vendors are registered next, also by `RegionalOps`. Each vendor has a legal `name` and a `vendor_code` of the letter V followed by exactly six digits, unique across vendors. A vendor's lifecycle `status` begins as `ACTIVE` and may later move to `SUSPENDED` or `DEACTIVATED` (§3.6). Two compliance figures are computed, never supplied: `compliance_score_bp`, a rolling score in basis points where 10000 is perfect, initialized to 10000 at creation; and `total_chargeback_cents`, the cumulative amount of confirmed chargebacks, initialized to 0.

Clubs belong to a region through `region_id`. A club's `name` and its positive, unique `club_number` are supplied at creation, as are `floor_slot_capacity` — the total number of pallet floor slots on the sales floor, at least 1, with no backroom overflow anywhere in the model — and `member_base`, the active membership count. Each club also carries `ancillary_flags`, an object of three booleans keyed `gas`, `pharmacy`, and `optical`, defaulting to all-false when omitted, which gate ancillary sales (§3.5). Two fields are derived: `allocated_slot_count`, the sum of reserved slots over the club's live allocations, starting at 0; and `posture`, the club's operating posture, initialized to `NORMAL`.

Depots are created by a `DepotManager` against a `region_id` and `name`, with a `dock_count` of at least 1 receiving doors. Dock operating hours are given as `dock_hours_open` and `dock_hours_close` in 24-hour HH:MM form, with close strictly after open, and `slot_length_minutes` — the granularity of bookable appointment windows — must divide 60 and be at least 15.

Items are the heart of merchandise setup. A `CategoryManager` creates an item under a supplying vendor via `vendor_id`, with a seven-digit numeric `sku` (unique), a free-text `description`, and the physical design parameters: `case_pack_qty` (selling units per case, at least 1), `pallet_length_in` and `pallet_width_in` (the pallet footprint in inches, each greater than zero), `cases_per_layer` (at least 1), and `max_layers` (at least 1). The `item_type` is either `REGULAR` for replenishable merchandise or `TREASURE_HUNT` for one-time-buy items that will never be reordered. Optional merchandising controls include `member_purchase_cap` (per-membership purchase cap in units per cap window, default 0 meaning uncapped), `sell_through_target_pct` (greater than 0 and at most 100, default 80), and `exit_window_date` — the YYYY-MM-DD date by which a treasure-hunt item faces mandatory markdown evaluation, required exactly when `item_type` is `TREASURE_HUNT` and meaningless otherwise.

From those inputs the system derives the pallet design. `pallet_qty_units` is the product of `case_pack_qty`, `cases_per_layer`, and `max_layers`. `pallets_per_slot` is 1 when the pallet footprint — the product of `pallet_length_in` and `pallet_width_in` — is at most the standard floor-slot area of 48 inches by 40 inches, and 2 when the footprint exceeds it. Both figures are computed at creation and recomputed at activation; an item also carries `complaint_weighted_score` and `complaint_count`, both initialized to 0 and maintained by the complaint machinery of §3.7. A new item begins life in `DRAFT`.

Activation, performed by a `CategoryManager`, moves an item from `DRAFT` to `ACTIVE`. Activation requires the item to currently be `DRAFT` — anything else is `ERR_INVALID_STATE` — and requires `case_pack_qty`, `cases_per_layer`, and `max_layers` each to be at least 1; the activation recomputes `pallet_qty_units` and `pallets_per_slot` as it fires.

### 3.2. Vendor Delivery Appointments and the Receiving Dock

A `VendorRep` books a delivery appointment by naming the `depot_id`, the `vendor_id` (which must equal the representative's own vendor identity or the request fails with `ERR_FORBIDDEN`), the `delivery_date` on or after the current logical date, a `start_time` and `end_time` in HH:MM form, and the `pallet_count` of at least 1 pallet expected on the truck. The window must lie within the depot's dock hours and both endpoints must align to the depot's `slot_length_minutes` grid measured from `dock_hours_open`; `end_time` must be strictly after `start_time`, and the window is half-open — it occupies `[start_time, end_time)`. A window outside dock hours, misaligned to the slot grid, or violating these ordering rules is rejected with `ERR_APPOINTMENT_CONFLICT` (HTTP 409).

Windows do not overlap on a dock door. The server assigns the dock door itself — always the lowest-numbered door free for the requested window, breaking ties between candidate windows by window start and then by creation time — and two appointments whose half-open windows intersect on the same depot and door conflict; a booking that cannot be placed without overlap is rejected with `ERR_APPOINTMENT_CONFLICT`. The booking vendor must be `ACTIVE`; an appointment for a `SUSPENDED` or `DEACTIVATED` vendor is rejected with `ERR_INACTIVE_REFERENCE` (HTTP 422). A booked appointment starts in `BOOKED` with `checked_in_at` unset, `unload_fee_cents` 0, and `chargeback_cents` 0.

On the delivery date, a `DepotManager` checks the driver in. Check-in requires the appointment to be `BOOKED`, requires the current logical date to equal the appointment's `delivery_date`, and requires the current logical time to be at or before the appointment's `end_time`; a check-in after the window closes is rejected with `ERR_APPOINTMENT_CONFLICT`. A successful check-in stamps `checked_in_at` with the current logical timestamp and moves the appointment to `CHECKED_IN`. If the check-in time is later than `start_time` plus a fifteen-minute grace period, the system immediately assesses a `LATE_CHECKIN` chargeback (status `ASSESSED`) and adds its amount to the appointment's `chargeback_cents`.

If the logical clock advances past the end of the `delivery_date` with no check-in recorded, the appointment auto-transitions from `BOOKED` to `NO_SHOW`, and a `NO_SHOW` chargeback is assessed and added to `chargeback_cents` in the same pass.

A `VendorRep` may cancel their own appointment, but only while it is `BOOKED` and only while the current logical datetime is strictly before the window start on the delivery date. Cancellation moves the appointment to `CANCELLED` with no chargeback; the dock window is freed.

Completing an appointment is a `DepotManager` action. Completion requires the appointment to be `CHECKED_IN`, and it requires the count of pallet rows received under the appointment to exactly equal the booked `pallet_count` — otherwise the request fails with `ERR_INVALID_STATE` (HTTP 409). At completion the unload fee is computed and stamped into `unload_fee_cents`: the base fee is the booked `pallet_count` multiplied by a per-pallet fee of 4500 cents, then scaled by a tier multiplier — 1.00 when the booked count is at most 10 pallets, 1.15 when it is more than 10 and at most 25, and 1.30 when it exceeds 25 — with the product rounded half-up to whole cents. The exact-equality count check runs before the fee is stamped and before the appointment moves on, so an over-delivery — more pallet rows received than booked — fails with `ERR_INVALID_STATE` like any other mismatch, and no `OVER_PALLET_COUNT` chargeback is reachable at completion in practice; the chargeback formula of §3.6 nonetheless pins what such an assessment would be. On success the appointment ends in `COMPLETED`.

### 3.3. Pallet Receipt and the Same-Day Cross-Dock Run

Pallets are received by a `DepotManager` against a checked-in appointment. Receipt supplies the `appointment_id`, the `item_id`, and the physical `unit_qty` on the pallet, which must equal the item's `pallet_qty_units` exactly — a mismatch is a consistency failure rejected with `ERR_CONSTRAINT_VIOLATION` (HTTP 422). The appointment must be `CHECKED_IN`; the item must be `ACTIVE` and the delivering vendor must be `ACTIVE`, with violations rejected as `ERR_INACTIVE_REFERENCE`. The receipt stamps `received_at` with the current logical timestamp and `received_date` with the current logical date — this date is the linchpin of the same-day cross-dock rule. A treasure-hunt reorder guard applies at receipt: if any markdown decision with outcome `MARKDOWN` exists for the item, receiving further pallets for it is rejected with `ERR_MARKDOWN_RULE_VIOLATION` (HTTP 422), because treasure-hunt items are never reordered. A received pallet begins in `RECEIVED`.

A `DepotPlanner` opens a cross-dock run by naming the `depot_id`, the `run_date` the run reallocates pallets for, and a `cutoff_time` in HH:MM form on that date. The run opens in `OPEN` with `committed_at` unset.

Proposing an allocation is the planner's core move, and it is the most heavily guarded write in the system. The request names the `pallet_id`, the destination `club_id`, the OCC witness `expected_cross_dock_run_version` (§2.7), and optionally `regional_ops_approved`. Within the endpoint, checks fire in this order: request shape, reference existence, state admissibility, the OCC stale-version check, the safety gates, the cutoff, the same-day rule, and finally club capacity, before the score is computed and the row persisted.

The guards, in business terms: the run must be `OPEN` and the pallet must be `RECEIVED`, else `ERR_INVALID_STATE`. The destination club's posture must not be `FROZEN`, else `ERR_CLUB_FROZEN` (HTTP 422). If the destination club is `CONSTRAINED`, the request must carry `regional_ops_approved` set to true, else `ERR_SAFETY_GATE` (HTTP 422). The current logical time on the run date must be at or before the run's `cutoff_time` — equality is allowed — else `ERR_CUTOFF_PASSED` (HTTP 422); after the cutoff the run accepts neither allocations nor commits. The pallet's `received_date` must equal the run's `run_date` — same-day cross-dock only, no overnight holds — else `ERR_SAME_DAY_ONLY` (HTTP 422). Finally, the allocation must not push the club's `allocated_slot_count` above its `floor_slot_capacity`; landing exactly at capacity is allowed, but exceeding it is rejected with `ERR_CLUB_CAPACITY_EXCEEDED` (HTTP 422) because there is no backroom.

A successful proposal computes the allocation's priority. The **velocity** input is the total `unit_qty` over `COMPLETED` purchases of the pallet's item at the destination club whose `cap_window` falls within the trailing window — the seven days ending the day before `run_date` for a `REGULAR` item, or the three days ending the day before `run_date` for a `TREASURE_HUNT` item, whose shallower history demands the shorter window. The **demographics factor** is 1 plus one-half times the club's `member_base` capped at 200000 members, divided by that cap. The **income factor** is 1 plus three-tenths times the owning region's `avg_member_income_cents` capped at 20000000 cents, divided by that cap. The `allocation_score` is the sum of velocity and a base of 10, multiplied by both factors, rounded half-up to four decimal places with intermediates unrounded. `floor_slots_reserved` equals the item's `pallets_per_slot`.

The new allocation is `PROPOSED`, and its `run_version` field echoes the parent run's `version` after this write — that is, the run's version the client should quote next — so planners can chain allocations without re-reading the run. Three cascades fire atomically with the proposal: the pallet moves from `RECEIVED` to `ALLOCATED`; the club's `allocated_slot_count` increases by `floor_slots_reserved` and its `posture` is recomputed (§3.4); and the parent run's `version` increments by 1.

A planner may void a `PROPOSED` allocation, optionally recording a `void_reason`. Voiding moves the allocation to `VOIDED`, decrements the club's `allocated_slot_count` by `floor_slots_reserved`, recomputes the club's posture, returns the pallet from `ALLOCATED` to `RECEIVED`, and increments the parent run's `version` by 1.

Committing a run is atomic and two-phased. The run must be `OPEN`, and the current logical time on the run date must be at or before `cutoff_time`, else `ERR_CUTOFF_PASSED`. Phase one moves every `PROPOSED` allocation to `COMMITTED`, locking each club's slot reservation — but if any destination club's posture is `FROZEN`, the entire commit fails with `ERR_CLUB_FROZEN` and no allocation transitions at all. Phase two then moves every `COMMITTED` allocation to `SHIPPED`, processing them in descending `allocation_score` with `created_at` ascending as the tie-break, and each shipped allocation's pallet moves from `ALLOCATED` to `SHIPPED`. The run itself lands in `COMMITTED`, `committed_at` is set, and the run's `version` increments by 1.

Cancelling an `OPEN` run moves it to `CANCELLED`, voids every `PROPOSED` allocation with `void_reason` set to the string `RUN_CANCELLED`, returns those pallets from `ALLOCATED` to `RECEIVED`, and decrements club slot counts with postures recomputed.

Pallets that outlive their day are stranded. When the logical clock advances past a pallet's `received_date` while the pallet is still `RECEIVED`, it auto-transitions to `STRANDED`. A `DepotManager` may reconcile a `STRANDED` pallet, moving it to `RECONCILED`; reconciliation is audit-only and restores no inventory. Pallets in `SHIPPED` or `RECONCILED` are terminal.

### 3.4. Club Posture: The Capacity Ladder

A club's `posture` is fully derived — never set directly — from the ratio of `allocated_slot_count` to `floor_slot_capacity`, recomputed after every allocation create, void, commit, or cascade that touches the club. The ladder uses a threshold equal to 80 percent of `floor_slot_capacity`, computed as integer floor division: the capacity times 80, divided by 100, rounded down.

A club is `FROZEN` when its `allocated_slot_count` is at least its `floor_slot_capacity`. Short of that, it is `CONSTRAINED` when `allocated_slot_count` is strictly greater than the 80-percent threshold. Otherwise it is `NORMAL`. Because recompute happens after every change, a club climbs and descends the ladder freely: `NORMAL` to `CONSTRAINED` when it crosses above the threshold, `CONSTRAINED` back to `NORMAL` when it falls to the threshold or below, `CONSTRAINED` to `FROZEN` at full capacity, `FROZEN` to `CONSTRAINED` when it drops strictly below capacity while remaining above the threshold, and `FROZEN` to `NORMAL` when it falls to the threshold or below. A single large allocation can also jump a club directly from `NORMAL` to `FROZEN` when it crosses both thresholds at once.

Posture is not cosmetic. Allocations into a `CONSTRAINED` club require the `regional_ops_approved` flag (§3.3), and any allocation into a `FROZEN` club — whether proposed individually or encountered during run commit — is rejected with `ERR_CLUB_FROZEN`, atomically aborting a commit that touches one.

### 3.5. Members, Purchases, Caps, and Ancillary Departments

The `MembershipDesk` registers members under a home club via `club_id`. Each member has a `membership_number` of the letter M followed by exactly nine digits (unique), a `tier` of either `GOLD_STAR` or `EXECUTIVE`, and a `household_size` of at least 1 (default 1) that later feeds complaint weighting. Members begin `ACTIVE`; the desk may suspend a member, moving them to `SUSPENDED`.

Recording a purchase requires `member_id`, `club_id`, `item_id`, and a `unit_qty` of at least 1. The purchasing member must be `ACTIVE` — a suspended member buying merchandise, filing a complaint, or purchasing an ancillary service is rejected with `ERR_SAFETY_GATE` — and the item must be `ACTIVE`, else `ERR_INACTIVE_REFERENCE`. The system stamps `purchased_at` from the logical clock and sets `cap_window` to the current logical date: cap windows are per-day.

The per-membership cap is enforced only when the item's `member_purchase_cap` is greater than zero. Usage is the sum of `unit_qty` over the member's `COMPLETED` purchases of that item whose `cap_window` equals the current logical date. The purchase passes when that usage plus the requested `unit_qty` is at most the cap — equality is allowed — and is rejected with `ERR_MEMBER_CAP_EXCEEDED` (HTTP 422) only when the sum would exceed the cap. A purchase begins `COMPLETED`; refunding it moves it to `REFUNDED` and reduces the member's cap usage for that `cap_window` by the purchase's `unit_qty`, since refunded purchases no longer count. Completed purchases feed both the allocation velocity window (§3.3) and the sell-through computation (§3.8).

Ancillary department sales tie the warehouse to its gas, pharmacy, and optical businesses. Recording one takes `club_id`, `member_id`, a `department` of `GAS`, `PHARMACY`, or `OPTICAL`, and an `amount_cents` of at least 1, and stamps `sold_on` with the current logical date. The member must be `ACTIVE` (the same safety gate), and the named department must be enabled in the club's `ancillary_flags`; a sale to a disabled department is rejected with `ERR_DEPARTMENT_DISABLED` (HTTP 422).

### 3.6. Chargebacks, Appeals, and Vendor Compliance

Chargebacks arise from three violations: `LATE_CHECKIN` assessed at check-in past the grace period, `NO_SHOW` assessed at day rollover, and `OVER_PALLET_COUNT` whose assessment rule applies when more pallets arrive than booked — though completion's exact-equality gate (§3.2) means no over-count appointment ever reaches that point, so in practice only `LATE_CHECKIN` and `NO_SHOW` chargebacks are ever created. Each chargeback carries the `vendor_id`, the originating `appointment_id`, the violation `reason`, an `assessed_at` timestamp from the logical clock, and a computed `amount_cents` that is always positive. A chargeback begins `ASSESSED`.

The assessment amount is computed in a pinned order: base by reason first, then per-extra-pallet penalty, then the repeat-offender multiplier. The base is 15000 cents for `LATE_CHECKIN`, 75000 cents for `NO_SHOW`, and 25000 cents for `OVER_PALLET_COUNT`. For an over-pallet-count violation only, the base gains 6000 cents for every received pallet beyond the booked `pallet_count` (and never below zero extra). The subtotal is then multiplied by a repeat multiplier of 1 plus one-quarter times the vendor's count of `CONFIRMED` chargebacks assessed within the trailing 90 days inclusive, with that count capped at 4 priors; the result is rounded half-up to whole cents. Assessment amounts are frozen at the terminal observation point — check-in for lateness, day rollover for no-show, completion for over-count — and never recomputed.

A `VendorRep` may appeal an `ASSESSED` chargeback on their own vendor (identity mismatch is `ERR_FORBIDDEN`), moving it to `APPEALED`. A `DepotManager` then resolves the appeal with an `outcome` field: `CONFIRM` moves the chargeback to `CONFIRMED`, `WAIVE` moves it to `WAIVED`. If the clock advances more than seven days past the `assessed_at` date while the chargeback is still `ASSESSED` and never appealed, it auto-confirms to `CONFIRMED`.

Confirming a chargeback — by resolution or by auto-confirm — adds its `amount_cents` to the vendor's `total_chargeback_cents` and recomputes the vendor's `compliance_score_bp`. Waived chargebacks never count toward either figure, though a waiver still triggers the recompute.

The compliance score starts from a perfect 10000 basis points and subtracts decayed penalties over the vendor's `CONFIRMED` chargebacks assessed within the trailing 90 days inclusive. Each chargeback's raw penalty is 250 for `LATE_CHECKIN`, 600 for `NO_SHOW`, and 400 for `OVER_PALLET_COUNT`. The penalty decays by age: a chargeback at most 30 days old counts in full, one 31 to 60 days old counts halved, and one 61 to 90 days old counts quartered — each 30-day bucket right-shifts the integer penalty by one bit. The score is 10000 minus the sum of decayed penalties, floored at zero. If the recomputed score falls below 8500 basis points while the vendor is `ACTIVE`, the vendor cascades to `SUSPENDED`, and a suspended vendor can no longer book new appointments — attempts are rejected with `ERR_INACTIVE_REFERENCE`.

A `DepotManager` may reinstate a `SUSPENDED` vendor back to `ACTIVE`, or deactivate a `SUSPENDED` vendor to the terminal `DEACTIVATED`. Deactivation is guarded: if any appointment for the vendor is still `BOOKED` or `CHECKED_IN`, the request fails with `ERR_REFERENTIAL_GUARD` (HTTP 409). A deactivated vendor's items remain, but new pallets cannot be received from it because receipt requires an `ACTIVE` vendor.

### 3.7. Complaints and Item Deletion Review

Members complain about items through the `MembershipDesk`, supplying `member_id`, `item_id`, and a `category` of `QUALITY`, `AVAILABILITY`, `PRICING`, or `SAFETY`. The complaining member must be `ACTIVE` under the same safety gate as purchases. The complaint is stamped with `created_on`, the current logical date, and begins `OPEN`.

Each complaint's `weight` is computed once at creation and frozen: a category multiplier — 4.0 for `SAFETY`, 2.0 for `QUALITY`, 1.5 for `AVAILABILITY`, 1.0 for `PRICING` — times the member's `household_size` at that moment. The item's `complaint_weighted_score` is the sum of `weight` over its `OPEN` complaints whose `created_on` falls within the trailing 30 days inclusive of the current logical date, rounded half-up to two decimal places, and `complaint_count` is the count of those complaints. Both figures are stored snapshots: they recompute only when a complaint is created, when a complaint is resolved — a resolved complaint is excluded — and when deletion review opens. The mere passage of the logical clock does not recompute them; a complaint that ages out of the trailing window leaves the stored figures untouched until the next create, resolve, or deletion-review-open event, so the figures visible between those events may reflect the window as of the last recomputation rather than the window at read time.

Deletion review is the item's off-ramp, driven by a `CategoryManager` through a single action with an optional `decision` field. Calling it without a decision on an `ACTIVE` item moves the item to `DELETION_REVIEW` and recomputes `complaint_weighted_score` and `complaint_count` from the trailing-30-day window so the manager reviews fresh numbers. Calling it on a `DELETION_REVIEW` item with `decision` equal to `REJECT` cycles the item back to `ACTIVE` with no field mutations beyond the usual `updated_at` and `version` bump. Calling it with `decision` equal to `APPROVE` discontinues the item — but only when `complaint_weighted_score` is at least 25.0; below that threshold the approval is rejected with `ERR_REFERENTIAL_GUARD`, because an item may not be deleted over lukewarm member sentiment.

Discontinuation, by whatever path, is a heavy cascade. Every pallet of the item in `RECEIVED` or `ALLOCATED` becomes `STRANDED`. For each stranded pallet that was `ALLOCATED`, its `PROPOSED` allocation becomes `VOIDED` first with `void_reason` set to the string `ITEM_DISCONTINUED`, and each such void decrements the destination club's `allocated_slot_count` by the allocation's `floor_slots_reserved` and recomputes the club's posture. Unlike a planner-initiated void, the cascade never returns the pallet to `RECEIVED` — it is stranded for good, awaiting reconciliation. The item ends in the terminal `DISCONTINUED` state.

### 3.8. Treasure-Hunt Sell-Through and Markdown Decisions

Treasure-hunt items live under a sell-through-or-markdown discipline with no reorder. A `CategoryManager` records a decision against an item by supplying `decision` — `SELL_THROUGH` or `MARKDOWN` — together with the OCC witness `expected_item_version` (§2.7), an optional `note` defaulting to empty, and `markdown_pct` when marking down: the percentage is required exactly when `decision` is `MARKDOWN`, must then be greater than 0 and less than 100, and its absence or presence in the wrong combination is rejected with `ERR_MARKDOWN_RULE_VIOLATION`.

Recording a decision recomputes the item's sell-through. The `sell_through_pct` stamped onto the decision is one hundred times the units sold — the sum of `unit_qty` over the item's `COMPLETED` purchases — divided by the units received, the sum of `unit_qty` over the item's pallets in `RECEIVED`, `ALLOCATED`, or `SHIPPED`, with the denominator floored at 1 to avoid division by zero; the quotient is rounded half-up to an integer percent. The system also records `decided_by_role` and `decided_at` from the acting context and logical clock, and the write increments the item's `version` by 1 and refreshes its `updated_at` — which is exactly why a second decider working from a stale read is rejected with `ERR_STALE_ITEM_VERSION`.

The mandatory-markdown rule binds at the exit window. When the current logical date is on or after the item's `exit_window_date` and the recomputed `sell_through_pct` is below the item's `sell_through_target_pct`, the only lawful decision is `MARKDOWN`; a `SELL_THROUGH` decision in that situation is rejected with `ERR_MARKDOWN_RULE_VIOLATION`. The same error enforces the no-reorder rule on the receiving dock: once any `MARKDOWN` decision exists for an item, receiving further pallets of it is refused (§3.3).

A treasure-hunt item with a recorded `MARKDOWN` decision may also be discontinued directly by a `CategoryManager`, skipping deletion review entirely: the direct path requires the item to be `ACTIVE`, requires `item_type` to be `TREASURE_HUNT`, and requires an existing `MARKDOWN` decision for the item — without one the request is rejected with `ERR_REFERENTIAL_GUARD`. The cascade is identical to deletion-review approval: unshipped pallets strand, their proposed allocations void with `void_reason` set to `ITEM_DISCONTINUED`, and club slot counts and postures recompute.

## 4. Endpoint Definitions

All resources are mounted under the `/wcd` prefix. Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource, and all reads, respond with HTTP 200. Request and response details beyond this table are governed by §2 and the workflow narratives of §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /wcd/regions | Create a region | RegionalOps |
| GET | /wcd/regions | List regions (`limit`, `offset`, `code`) | RegionalOps, CategoryManager, DepotManager, DepotPlanner, MembershipDesk, VendorRep |
| GET | /wcd/regions/{id} | Get a region | RegionalOps, CategoryManager, DepotManager, DepotPlanner, MembershipDesk, VendorRep |
| POST | /wcd/vendors | Create a vendor (compliance score initialized to 10000) | RegionalOps |
| GET | /wcd/vendors | List vendors (`limit`, `offset`, `status`) | RegionalOps, DepotManager, DepotPlanner, VendorRep, CategoryManager |
| GET | /wcd/vendors/{id} | Get a vendor | RegionalOps, DepotManager, DepotPlanner, VendorRep, CategoryManager |
| GET | /wcd/vendors/{id}/appointments | List a vendor's appointments (`limit`, `offset`, `status`, `delivery_date`) | RegionalOps, DepotManager, VendorRep |
| POST | /wcd/vendors/{id}/reinstate | Reinstate a suspended vendor to ACTIVE | DepotManager |
| POST | /wcd/vendors/{id}/deactivate | Deactivate a suspended vendor (guarded by open appointments) | DepotManager |
| POST | /wcd/clubs | Create a club (posture NORMAL, allocated slots 0) | RegionalOps |
| GET | /wcd/clubs | List clubs (`limit`, `offset`, `region_id`, `posture`) | RegionalOps, CategoryManager, DepotManager, DepotPlanner, MembershipDesk, VendorRep |
| GET | /wcd/clubs/{id} | Get a club | RegionalOps, CategoryManager, DepotManager, DepotPlanner, MembershipDesk, VendorRep |
| GET | /wcd/clubs/{id}/members | List a club's members (`limit`, `offset`, `status`) | RegionalOps, MembershipDesk, CategoryManager |
| GET | /wcd/clubs/{id}/allocations | List allocations targeting a club (`limit`, `offset`, `status`) | RegionalOps, DepotPlanner, DepotManager |
| GET | /wcd/clubs/{id}/department-sales | List a club's ancillary sales (`limit`, `offset`, `department`, `sold_on`) | RegionalOps, MembershipDesk, CategoryManager |
| GET | /wcd/clubs/{id}/purchases | List purchases at a club (`limit`, `offset`, `status`, `cap_window`) | RegionalOps, MembershipDesk, CategoryManager |
| POST | /wcd/items | Create an item in DRAFT (pallet fields computed) | CategoryManager |
| GET | /wcd/items | List items (`limit`, `offset`, `status`, `item_type`, `vendor_id`) | RegionalOps, CategoryManager, DepotManager, DepotPlanner, MembershipDesk, VendorRep |
| GET | /wcd/items/{id} | Get an item | RegionalOps, CategoryManager, DepotManager, DepotPlanner, MembershipDesk, VendorRep |
| POST | /wcd/items/{id}/activate | Activate a draft item (recomputes pallet fields) | CategoryManager |
| POST | /wcd/items/{id}/request-deletion | Open deletion review or resolve it via `decision` (APPROVE/REJECT) | CategoryManager |
| POST | /wcd/items/{id}/discontinue | Directly discontinue a TREASURE_HUNT item with a MARKDOWN decision | CategoryManager |
| GET | /wcd/items/{id}/markdown-decisions | List an item's markdown decisions (`limit`, `offset`) | CategoryManager, RegionalOps |
| POST | /wcd/items/{item_id}/markdown-decisions | Record a sell-through-or-markdown decision (OCC on item version) | CategoryManager |
| GET | /wcd/items/{id}/complaints | List an item's complaints (`limit`, `offset`, `status`, `category`) | CategoryManager, MembershipDesk, RegionalOps |
| POST | /wcd/depots | Create a depot | DepotManager |
| GET | /wcd/depots | List depots (`limit`, `offset`, `region_id`) | RegionalOps, DepotManager, DepotPlanner, VendorRep |
| GET | /wcd/depots/{id} | Get a depot | RegionalOps, DepotManager, DepotPlanner, VendorRep |
| GET | /wcd/depots/{id}/appointments | List a depot's appointments (`limit`, `offset`, `delivery_date`, `status`, `vendor_id`) | RegionalOps, DepotManager, DepotPlanner, VendorRep |
| GET | /wcd/depots/{id}/cross-dock-runs | List a depot's cross-dock runs (`limit`, `offset`, `run_date`, `status`) | RegionalOps, DepotManager, DepotPlanner |
| POST | /wcd/appointments | Book a delivery appointment (half-open window, server-assigned dock door; rep must own the vendor) | VendorRep |
| GET | /wcd/appointments/{id} | Get an appointment | RegionalOps, DepotManager, DepotPlanner, VendorRep |
| POST | /wcd/appointments/{id}/check-in | Driver check-in on the delivery date (possible LATE_CHECKIN chargeback) | DepotManager |
| POST | /wcd/appointments/{id}/complete | Complete unloading; computes unload fee; possible OVER_PALLET_COUNT chargeback | DepotManager |
| POST | /wcd/appointments/{id}/cancel | Vendor cancels own appointment before window start | VendorRep |
| GET | /wcd/appointments/{id}/pallets | List pallets received under an appointment (`limit`, `offset`, `status`) | RegionalOps, DepotManager, DepotPlanner, VendorRep |
| POST | /wcd/pallets | Receive a pallet under a CHECKED_IN appointment | DepotManager |
| GET | /wcd/pallets | List pallets (`limit`, `offset`, `status`, `item_id`, `appointment_id`, `received_date`) | RegionalOps, DepotManager, DepotPlanner |
| GET | /wcd/pallets/{id} | Get a pallet | RegionalOps, DepotManager, DepotPlanner |
| POST | /wcd/pallets/{id}/reconcile | Reconcile a stranded pallet (audit-only) | DepotManager |
| POST | /wcd/cross-dock-runs | Open a cross-dock run for a depot and date | DepotPlanner |
| GET | /wcd/cross-dock-runs/{id} | Get a cross-dock run | RegionalOps, DepotManager, DepotPlanner |
| POST | /wcd/cross-dock-runs/{run_id}/allocations | Propose an allocation (OCC on run version; guarded by posture, cutoff, same-day, capacity) | DepotPlanner |
| GET | /wcd/cross-dock-runs/{run_id}/allocations | List allocations in a run (`limit`, `offset`, `status`, `club_id`) | RegionalOps, DepotManager, DepotPlanner |
| GET | /wcd/allocations | List allocations across runs (`limit`, `offset`, `status`, `pallet_id`, `club_id`, `cross_dock_run_id`) | RegionalOps, DepotManager, DepotPlanner |
| POST | /wcd/cross-dock-runs/{run_id}/commit | Commit the run (two-phase, atomic against FROZEN clubs) | DepotPlanner |
| POST | /wcd/cross-dock-runs/{run_id}/cancel | Cancel an OPEN run; voids proposed allocations and frees pallets | DepotPlanner |
| GET | /wcd/allocations/{id} | Get an allocation | RegionalOps, DepotManager, DepotPlanner |
| POST | /wcd/allocations/{id}/void | Void a PROPOSED allocation; frees pallet and slots | DepotPlanner |
| POST | /wcd/members | Register a member | MembershipDesk |
| GET | /wcd/members | List members (`limit`, `offset`, `club_id`, `status`, `tier`) | MembershipDesk, RegionalOps, CategoryManager |
| GET | /wcd/members/{id} | Get a member | MembershipDesk, RegionalOps, CategoryManager |
| POST | /wcd/members/{id}/suspend | Suspend a member | MembershipDesk |
| GET | /wcd/members/{id}/purchases | List a member's purchases (`limit`, `offset`, `item_id`, `cap_window`, `status`) | MembershipDesk, RegionalOps, CategoryManager |
| GET | /wcd/members/{id}/complaints | List a member's complaints (`limit`, `offset`, `status`, `item_id`) | MembershipDesk, CategoryManager, RegionalOps |
| GET | /wcd/members/{id}/department-sales | List a member's ancillary sales (`limit`, `offset`, `department`) | MembershipDesk, RegionalOps, CategoryManager |
| POST | /wcd/purchases | Record a member purchase (per-day cap enforced) | MembershipDesk |
| GET | /wcd/purchases | List purchases (`limit`, `offset`, `member_id`, `club_id`, `item_id`, `cap_window`, `status`) | MembershipDesk, RegionalOps, CategoryManager |
| GET | /wcd/purchases/{id} | Get a purchase | MembershipDesk, RegionalOps, CategoryManager |
| POST | /wcd/purchases/{id}/refund | Refund a completed purchase (reverses cap usage) | MembershipDesk |
| POST | /wcd/complaints | File a member complaint against an item | MembershipDesk |
| GET | /wcd/complaints/{id} | Get a complaint | MembershipDesk, CategoryManager, RegionalOps |
| POST | /wcd/complaints/{id}/resolve | Resolve an open complaint (recomputes item complaint figures) | MembershipDesk |
| GET | /wcd/chargebacks | List chargebacks (`limit`, `offset`, `vendor_id`, `appointment_id`, `status`, `reason`) | RegionalOps, DepotManager, VendorRep |
| GET | /wcd/chargebacks/{id} | Get a chargeback | RegionalOps, DepotManager, VendorRep |
| POST | /wcd/chargebacks/{id}/appeal | Vendor appeals own assessed chargeback | VendorRep |
| POST | /wcd/chargebacks/{id}/resolve | Resolve an appealed chargeback via `outcome` (CONFIRM/WAIVE) | DepotManager |
| POST | /wcd/department-sales | Record an ancillary department sale (department must be enabled) | MembershipDesk |
| GET | /wcd/department-sales/{id} | Get a department sale | MembershipDesk, RegionalOps, CategoryManager |
| POST | /wcd/_clock/set_current_utc | Advance the logical clock; fires no-show rollover, pallet stranding, and chargeback auto-confirm | RegionalOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SAFETY_GATE | 422 |
| ERR_DEPARTMENT_DISABLED | 422 |
| ERR_CLUB_FROZEN | 422 |
| ERR_APPOINTMENT_CONFLICT | 409 |
| ERR_CUTOFF_PASSED | 422 |
| ERR_CONSTRAINT_VIOLATION | 422 |
| ERR_SAME_DAY_ONLY | 422 |
| ERR_MEMBER_CAP_EXCEEDED | 422 |
| ERR_CLUB_CAPACITY_EXCEEDED | 422 |
| ERR_MARKDOWN_RULE_VIOLATION | 422 |
| ERR_INACTIVE_REFERENCE | 422 |
| ERR_REFERENTIAL_GUARD | 409 |
| ERR_STALE_RUN_VERSION | 412 |
| ERR_STALE_ITEM_VERSION | 412 |
