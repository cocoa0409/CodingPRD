# Salvage Vehicle Online Auction, Member Licensing & Title Processing API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Salvage Vehicle Online Auction API, a platform in the mold of a full-service salvage marketplace connecting insurance sellers, dismantlers, dealers, and export buyers. The platform governs the complete journey of a salvage vehicle: an insurer assigns the vehicle to a physical yard; yard staff document condition through imaging, damage coding, and run-and-drive verification; title clerks record title acquisition and its jurisdiction-driven transferability; buyers — whose purchasing power is shaped by a tier system and state-issued dealer, dismantler, or salvage-broker licenses — place preliminary and live bids in sequenced online auctions; and finally the winning buyer settles payment, books a load-out slot against yard capacity, and drives the vehicle out through a gate pass, while the seller receives a net settlement after fees, storage recovery, and title-timing penalties.

Three concerns dominate the design. First, **compliance**: title types (clean, salvage, rebuilt, non-repairable, parts-only, certificate-of-destruction) interact with the title jurisdiction in ways that determine whether a vehicle can transfer to a US buyer at all, must be exported, or can never transfer — and state licensing law gates which buyers may even place a bid on which lot. Second, **money**: a tiered buyer premium, two seller fee schedules, dual-sided storage fees with different free-day allowances for buyer and seller, and a flat penalty for late title acquisition all feed a single settlement waterfall whose evaluation order is pinned to the cent. Third, **operational determinism**: auctions run lots in a deterministic sequence, bid acceptance depends on a logical clock rather than wall time, and every rule in this document is evaluated against that clock so behavior is reproducible.

The API is mounted under the `/salvage-auction` path prefix. All datetimes, deadlines, license-expiry comparisons, and storage-day computations read from a single logical clock; before any administrative clock-setting call is made, the logical clock reads exactly `2026-09-01T00:00:00Z` and must never fall back to wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts: authentication, response envelopes, pagination, common resource properties, monetary precision, the logical clock, nested-resource validation, and the concurrency discipline that guards the one readiness decision in the system that can silently rest on superseded data.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming one of the declared roles. The recognized roles are `PlatformAdmin`, `SellerAgent`, `YardOperator`, `Auctioneer`, `Buyer`, and `TitleClerk`. A request with a missing header or a role name outside this declared set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but not permitted for the endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403). The role-to-endpoint matrix is fixed in §4.

Identity semantics differ by role. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` — a bid's `member_id`, a sale's `winner_member_id`, a gate pass or export document reached through a sale — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `SellerAgent`, `X-User-ID` is the `id` of the acting `Seller`; operations on vehicles and sales are permitted only when the vehicle's `seller_id` equals `X-User-ID` (a mismatch on an on-approval decision surfaces as `ERR_SELLER_MISMATCH`). When `X-User-Role` is `PlatformAdmin`, `YardOperator`, `Auctioneer`, or `TitleClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every top-level resource — Yard, Seller, Member, License, Vehicle, TitleRecord, Auction, AuctionItem, Sale, GatePass, Settlement, and ExportDocument — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): a system-managed counter that increments by 1 on every mutation to the resource.

The Bid resource is the sole exception: as an immutable event row it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from Bid, and a bid's `id` is identity only — it is never used in running-order selection or bid-ranking decisions. Any state transition or computed-field change described in §3 constitutes a mutation of the affected resource and therefore bumps its `version` and refreshes its `updated_at`; where §3 names a specific increment (for example on the vehicle during readiness or lifecycle transitions), that increment is the same mechanism stated explicitly.

### 2.5. The Logical Clock

All time-dependent behavior in the system — auction start gating, license expiry, the gate-pass expiry window, storage-day counting, title-acquisition lateness, and every recorded timestamp — is evaluated against a single logical clock, never wall-clock time. Before any call to the administrative clock-setting capability, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance the logical clock to a supplied `to_iso8601` instant through the test-driving capability; the response reports the resulting `current_utc`. Timestamp fields such as `assigned_at`, `received_at`, `placed_at`, and `gate_pass_expires_at` all record values of this clock. These fields are rendered as ISO 8601 UTC instants that omit the fractional-seconds component when the recorded instant falls exactly on a whole second — so at the default logical clock they render exactly as `2026-09-01T00:00:00Z` — and carry three fractional digits when sub-second precision is non-zero.

### 2.6. Monetary Values, Units, and Precision

All monetary values are expressed and stored as integer **cents** — reserve prices, bid amounts, hammer prices, fees, and settlements alike. Wherever a rule produces a non-integral cent value, the rounding method is **round half up** to whole cents; the buyer premium applies this rounding per tier before summing (see §3.6). Day-granule computations — storage windows and the title SLA — operate on whole calendar days in the UTC date domain: a "storage day" is a whole calendar-day boundary crossed between two instants, so the day count between two timestamps is the difference of their UTC dates. For example, a vehicle received at `2026-09-01T23:00:00Z` and sold at `2026-09-03T00:30:00Z` has been held 2 storage days. Comparisons against dates (license expiry) use the UTC date part of the logical clock.

### 2.7. Nested Resource Retrieval and Validation Order

Requests that target nested resources validate path identifiers strictly left to right. A request addressed at a vehicle's title validates the vehicle before the title; an auction-item path validates the auction before the item; a gate-pass or export-document path validates the sale before the child. The request is rejected immediately with the 404 error corresponding to the first nonexistent identifier — `ERR_VEHICLE_NOT_FOUND`, `ERR_AUCTION_NOT_FOUND`, `ERR_AUCTION_ITEM_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_GATE_PASS_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, or `ERR_TITLE_NOT_FOUND` as applicable. Fetching a license by id that does not exist yields `ERR_LICENSE_NOT_FOUND`, and an unknown export document id yields `ERR_EXPORT_DOC_NOT_FOUND`. Request bodies that reference entities by id are likewise rejected with the matching 404 when the referenced entity does not exist: an unknown `yard_id` yields `ERR_YARD_NOT_FOUND`, an unknown `seller_id` yields `ERR_SELLER_NOT_FOUND`, an unknown `member_id` yields `ERR_MEMBER_NOT_FOUND`, an unknown `vehicle_id` yields `ERR_VEHICLE_NOT_FOUND`, an unknown `auction_id` yields `ERR_AUCTION_NOT_FOUND`, and an unknown `sale_id` yields `ERR_SALE_NOT_FOUND`.

Beyond existence, all validation across the API runs in a fixed priority order so that when several rules would reject the same request, the same error always surfaces. The order is: **(1)** authentication headers; **(2)** role permission and entity-backed ownership (`ERR_FORBIDDEN`); **(3)** path-identifier existence, left to right; **(4)** existence of body-referenced entities; **(5)** request shape — required fields present, types correct, enum values within their declared sets, the VIN exactly 17 characters, temporal ends strictly after starts, amounts strictly positive — any failure here is `ERR_INVALID_REQUEST` (HTTP 400); **(6)** uniqueness constraints (`ERR_EMAIL_TAKEN`, `ERR_VIN_DUPLICATE`, `ERR_TITLE_ALREADY_EXISTS`, `ERR_VEHICLE_ALREADY_LISTED`); **(7)** state preconditions for the requested transition (`ERR_VEHICLE_INVALID_STATE`, `ERR_VEHICLE_NOT_SALE_READY`, `ERR_AUCTION_NOT_SCHEDULED`, `ERR_AUCTION_NOT_LIVE`, `ERR_AUCTION_ITEM_NOT_QUEUED`, `ERR_AUCTION_ITEM_NOT_LIVE`, `ERR_AUCTION_ITEM_ALREADY_LIVE`, `ERR_AUCTION_ITEM_OUT_OF_ORDER`, `ERR_SALE_NOT_PENDING_APPROVAL`, `ERR_SALE_NOT_AWAITING_PAYMENT`, `ERR_SALE_NOT_CANCELLABLE`, `ERR_GATE_PASS_INVALID_STATE`, `ERR_VEHICLE_NOT_CANCELLABLE`); **(8)** license and title gating on bids and lot closure (`ERR_LICENSE_REQUIRED`, `ERR_MEMBER_SUSPENDED`, `ERR_TITLE_EXPORT_ONLY`, `ERR_TITLE_NON_TRANSFERABLE`); **(9)** bid-amount rules (`ERR_BID_INCREMENT_TOO_SMALL`, `ERR_BID_SELF_OUTBID`); **(10)** clock-based gates (`ERR_AUCTION_NOT_YET_STARTED`, `ERR_TITLE_NOT_RECEIVED`, `ERR_GATE_PASS_EXPIRED`); **(11)** export compliance at load-out (`ERR_EXPORT_DOCUMENT_REQUIRED`); **(12)** yard slot capacity (`ERR_SLOT_CAPACITY_EXCEEDED`); **(13)** payment exactness (`ERR_PAYMENT_AMOUNT_MISMATCH`); **(14)** reserve and no-bid handling at close (`ERR_RESERVE_NOT_MET`, `ERR_NO_BIDS`). So, for instance, a suspended member's malformed bid fails authentication of its shape before its suspension is ever examined, and an out-of-sequence lot opening is reported as such before any question of bid amounts arises.

### 2.8. Optimistic Concurrency Control

Exactly one write in the system is guarded by optimistic concurrency control: advancing a vehicle from `AWAITING_CONDITION` to `SALE_READY`. That request must carry `expected_vehicle_version` holding the caller's last-observed `version` of the vehicle. Because an intervening condition revision legitimately overwrites the very condition report the caller based its readiness judgment on, a value that no longer matches the vehicle's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than allowing the readiness decision to stand on superseded data. No other endpoint takes a version field; all other mutations are processed without an OCC check.

### 2.9. Seller and Yard Operational Status

Two top-level registries gate all downstream flow. A **Yard** is created with a `name`, a two-letter `state_code` (which drives both the licensing jurisdiction and the title jurisdiction for every vehicle stored there), a `daily_storage_rate_cents` that must be greater than zero, and a `free_storage_days` allowance that must be at least zero; it begins `ACTIVE` and may become `CLOSED`, in which state it rejects new vehicle assignments with `ERR_YARD_CLOSED` and new slot bookings. A **Seller** is created with a `name`, a `seller_type` of `INSURER`, `DEALER`, or `FLEET`, and a `fee_schedule` of `STANDARD` or `VOLUME` that selects the settlement fee schedule; it begins `ACTIVE` and may become `SUSPENDED`, in which state it cannot receive new vehicle assignments — assignment attempts are rejected with `ERR_SELLER_SUSPENDED`. A **Member** is registered with an `email` (unique per member), a `full_name`, a two-letter `home_state`, a `tier` of `BASIC`, `PREMIER`, or `BUSINESS`, and an optional `country_code` defaulting to `US`; members whose `country_code` is not `US` are exporters and require an export document per purchased vehicle. A member's `status` is `ACTIVE` or `SUSPENDED`; suspended members cannot bid.

## 3. Business Logic & Workflows

### 3.1. Vehicle Intake: Assignment, Imaging, and Condition Documentation

The lifecycle of a vehicle begins when a `SellerAgent` assigns it to a yard, submitting the `seller_id`, the `yard_id`, a 17-character `vin` that must be unique system-wide (a duplicate is rejected with `ERR_VIN_DUPLICATE`), the `year`, `make`, and `model`, the `lot_type` (`STANDARD`, `DEALER_ONLY`, `DISMANTLER_ONLY`, or `EXPORT_ONLY`), the `reserve_price_cents` floor (which must be at least zero), the `sale_type` (`PURE`, `MINIMUM_BID`, or `ON_APPROVAL`), the `odometer_reading` at assignment (at least zero), and optionally an initial `damage_codes` list. The new vehicle is stamped `ASSIGNED`, its `assigned_at` records the logical clock, and its condition fields initialize to `image_count` of 0, `primary_damage` of `NONE`, `run_and_drive_status` of `UNKNOWN`, and `title_brand` of `NONE`, with an empty `image_ids` list.

Condition documentation is the yard staff's work and has two halves that may interleave in either order. A `YardOperator` attaches condition images one at a time by submitting an `image_url`; the server mints each image id, appends it to `image_ids`, and returns the minted `image_id` together with the running `image_count`. The upload that brings the count to at least five automatically advances the vehicle from `ASSIGNED` to `AWAITING_CONDITION`; with fewer than five images the vehicle stays `ASSIGNED` and any readiness attempt is rejected with `ERR_VEHICLE_NOT_IMAGE_READY`. Independently, the operator submits a condition report carrying `primary_damage` (one of `FRONT`, `REAR`, `SIDE`, `TOP`, `MECHANICAL`, `FLOOD`, or `FIRE`), `run_and_drive_status` (one of `RUN_AND_DRIVE`, `STARTS`, or `STATIONARY`), and optionally a `damage_codes` list which, when present and non-empty, replaces the vehicle's list. A condition report submitted while the vehicle is still `ASSIGNED` is accepted and recorded the same way — this self-loop exists so that the order of imaging versus condition submission never changes the reachable set. Once the vehicle is `AWAITING_CONDITION`, further condition submissions act as unbounded revisions: each overwrites `primary_damage` and `run_and_drive_status`, replaces `damage_codes` when the payload carries a non-empty array, and increments the vehicle's `version` by 1. Submitting a condition report to a vehicle in any other status is rejected with `ERR_VEHICLE_INVALID_STATE`.

### 3.2. Title Acquisition and Jurisdictional Transferability

A `TitleClerk` records title acquisition for a vehicle by submitting the `title_type` — one of `CLEAN`, `SALVAGE`, `REBUILT`, `NON_REPAIRABLE`, `PARTS_ONLY`, or `CERTIFICATE_OF_DESTRUCTION`. Exactly one title record may exist per vehicle; a second attempt is rejected with `ERR_TITLE_ALREADY_EXISTS`, and title recording on a `CANCELLED` vehicle is rejected. Although the title lifecycle is documented as beginning in `PENDING`, that state is virtual: creation of the record is itself the receipt, and the row is persisted directly in `RECEIVED` with its `received_at` set to the logical clock. The record's `jurisdiction_state` is copied from the state of the vehicle's yard at creation and is immutable thereafter.

At issue, the record's `transferability` is derived from the pairing of jurisdiction and title type. `CLEAN`, `SALVAGE`, and `REBUILT` titles are `TRANSFERABLE` everywhere. A `PARTS_ONLY` title in California or Texas is `NON_TRANSFERABLE`, and `EXPORT_ONLY` in every other jurisdiction. A `NON_REPAIRABLE` title in Florida or Michigan is `NON_TRANSFERABLE`, and `EXPORT_ONLY` elsewhere. A `CERTIFICATE_OF_DESTRUCTION` is `NON_TRANSFERABLE` everywhere. This derivation is decisive downstream: a `NON_TRANSFERABLE` title can never produce a completed sale, and an `EXPORT_ONLY` title can only sell to a non-US buyer.

The title record also carries a `late` flag. When the elapsed time between the vehicle's `assigned_at` and the title's `received_at` exceeds thirty days — the boundary is strict, so exactly thirty days elapsed is not late — the flag is set true, and the seller's eventual settlement absorbs a flat 15000-cent penalty. The title record's terminal state, `TRANSFERRED`, is reached only as a side effect of a completed sale (§3.5).

### 3.3. Readiness and Listing: From Documented Vehicle to Queued Lot

When imaging and condition documentation are complete and the title is in hand, a `YardOperator` marks the vehicle ready. Five preconditions are enforced, and where several fail the priority order of §2.7 decides which error surfaces — with one endpoint-specific refinement: the image-readiness check precedes the state check, so a vehicle with fewer than five images surfaces `ERR_VEHICLE_NOT_IMAGE_READY` even when it is not in `AWAITING_CONDITION` (such a vehicle never left `ASSIGNED`). The preconditions, in the order they are checked: its `image_count` must be at least five (`ERR_VEHICLE_NOT_IMAGE_READY`); the vehicle must be in `AWAITING_CONDITION` (`ERR_VEHICLE_INVALID_STATE`); its `damage_codes` must be non-empty and a condition report must have been submitted at least once, meaning `primary_damage` is not `NONE` and `run_and_drive_status` is not `UNKNOWN` (`ERR_VEHICLE_INCOMPLETE_CONDITION`); a title record must exist in `RECEIVED` status (`ERR_TITLE_NOT_RECEIVED`); and the request must carry `expected_vehicle_version` matching the vehicle's current `version` per the OCC rule of §2.8 (`ERR_STALE_VERSION`). On success the vehicle becomes `SALE_READY`, its `received_at` is stamped with the logical clock — this timestamp later anchors the seller-side storage window — and its `version` increments.

An `Auctioneer` prepares a sale event by scheduling an auction with a `name` and a `scheduled_start` instant; the auction begins `SCHEDULED` with `current_sequence_number` at 0. Listing a vehicle into an auction creates an auction item referencing the `vehicle_id`. Listing requires the vehicle to be `SALE_READY` (`ERR_VEHICLE_NOT_SALE_READY`), the auction to be `SCHEDULED` (`ERR_AUCTION_NOT_SCHEDULED`), and no other item for the same vehicle to be `QUEUED` or `LIVE` (`ERR_VEHICLE_ALREADY_LISTED`). The new item is `QUEUED` with a null `sequence_number`, and the vehicle moves to `LISTED`. If the auctioneer withdraws the item before it runs — permitted only while the item is `QUEUED`, else `ERR_AUCTION_ITEM_NOT_QUEUED` — the item becomes `CANCELLED` and the vehicle returns to `SALE_READY`.

The auction itself goes live when the logical clock has reached its `scheduled_start` (a premature start is rejected with `ERR_AUCTION_NOT_YET_STARTED`), the auction is still `SCHEDULED`, and at least one item is queued (`ERR_AUCTION_EMPTY`). Going live assigns the deterministic running order: the candidate set is the auction's `QUEUED` items, ranked by their `created_at` ascending; if two items tie on `created_at`, the tie is broken by their vehicle's `vin` ascending lexicographically; `sequence_number` values 1 through N are assigned contiguously in that order. An auction with no remaining `QUEUED` or `LIVE` items — every item `CLOSED` or `CANCELLED` — automatically transitions to `COMPLETED`.

### 3.4. Live Bidding: Sequencing, Preliminary Bids, and the Hammer

Lots run strictly in their assigned order. Opening a lot requires the auction to be `LIVE` (`ERR_AUCTION_NOT_LIVE`), the item's `sequence_number` to be exactly one greater than the auction's `current_sequence_number` (skipping ahead is rejected with `ERR_AUCTION_ITEM_OUT_OF_ORDER`), and no other item in the same auction to be `LIVE` (`ERR_AUCTION_ITEM_ALREADY_LIVE`). Opening snapshots the preliminary market: `prelim_high_bid_cents` becomes the maximum of the bids placed while the item was queued (0 when there were none), `prelim_high_bidder_id` the member who placed it (null when none), and the live bookkeeping — `high_bid_cents`, `high_bidder_id` — initializes from that same snapshot. The `reserve_met` flag is set true exactly when the preliminary high bid is at least the vehicle's `reserve_price_cents`, the auction's `current_sequence_number` advances to the item's sequence number, and both the vehicle (to `LIVE`) and the auction increment their `version`.

A `Buyer` places a bid by submitting the `auction_item_id` and an `amount_cents` that must be greater than zero. The bid's `bid_type` is derived from the item's status at acceptance: `PRELIM` while the item is `QUEUED`, `LIVE` while it is `LIVE`. Before the amount is even examined, license eligibility is evaluated (§3.7) — gating failures surface as `ERR_LICENSE_REQUIRED`, `ERR_MEMBER_SUSPENDED`, or `ERR_TITLE_EXPORT_ONLY`. Amount rules then apply by bid type: a live bid must be at least the current `high_bid_cents` plus 2500 cents, the fixed minimum increment, else `ERR_BID_INCREMENT_TOO_SMALL`; a preliminary bid need only be positive. A member who is already the high bidder on the item may not outbid themself — such a bid is rejected with `ERR_BID_SELF_OUTBID`. Each accepted bid flips the previous winning bid's `is_winning` to false, sets its own `is_winning` to true, stamps `placed_at` with the logical clock, recomputes the item's `high_bid_cents`, `high_bidder_id`, and `reserve_met` (true exactly when the new high bid reaches the reserve), and increments the auction item's `version`. At most one bid per item is ever marked winning.

Falling the hammer — closing the live lot — branches on the vehicle's `sale_type`. Closing requires the item to be `LIVE` (`ERR_AUCTION_ITEM_NOT_LIVE`) and at least one bid to have been accepted, so `high_bid_cents` above zero (`ERR_NO_BIDS`). For `PURE` and `MINIMUM_BID` vehicles, `reserve_met` must also be true (`ERR_RESERVE_NOT_MET`), and the title must not be `NON_TRANSFERABLE` (`ERR_TITLE_NON_TRANSFERABLE`). A successful close of those sale types moves the vehicle `LIVE → SOLD` and produces a `Sale` in `AWAITING_PAYMENT` status: the `winning_bid_cents` and `winner_member_id` are copied from the item's high bid, the `buyer_fee_cents` is computed per the tiered premium of §3.6, and the `gate_pass_expires_at` is set to the logical clock plus 72 hours. Vehicles with `sale_type` `ON_APPROVAL` always route differently: regardless of whether the reserve was met, a close with bids moves the vehicle `LIVE → ON_APPROVAL_PENDING` and creates the `Sale` in `PENDING_APPROVAL` status with its buyer premium computed but no expiry stamped yet; the title-transferability gate still applies. In both branches the item becomes `CLOSED`, the winning bid's `is_winning` is locked true, and the vehicle's `version` increments.

### 3.5. Sale Decisions, Payment, and Unwinding

An on-approval sale waits for the owning seller's decision. Approval by the `SellerAgent` requires the sale to be `PENDING_APPROVAL` and to belong to the acting seller (violations surface as `ERR_SALE_NOT_PENDING_APPROVAL` or `ERR_SELLER_MISMATCH`) and the vehicle to be in `ON_APPROVAL_PENDING` (`ERR_VEHICLE_INVALID_STATE`); approval moves the sale to `AWAITING_PAYMENT`, stamps `gate_pass_expires_at` at the logical clock plus 72 hours, performs the full close side-effect set described below, and moves the vehicle to `SOLD`. Rejection requires only that the sale be `PENDING_APPROVAL` and seller-owned; it cancels the sale, releases the winning bid (`is_winning` back to false), and returns the vehicle to `SALE_READY` so it can be listed again.

Whichever path produced it, a completed sale triggers a fixed bundle of side effects at the moment it becomes `AWAITING_PAYMENT`. A `Settlement` is created in `DRAFT` status and computed per the waterfall of §3.6. The title record moves from `RECEIVED` to `TRANSFERRED`, and state-specific brand stamping applies: when the title type is `NON_REPAIRABLE` or `PARTS_ONLY` and the jurisdiction is Florida or Michigan, the vehicle's `title_brand` is force-set to `REBUILT` — in practice reachable through `PARTS_ONLY`, since a `NON_REPAIRABLE` title in those two states is `NON_TRANSFERABLE` and can never have reached this point. When the winning member's `country_code` is not `US`, an export-document requirement attaches to the sale: load-out will require a `VERIFIED` export document (§3.8).

Payment is the buyer's act, on their own sale only, with the sale in `AWAITING_PAYMENT` (`ERR_SALE_NOT_AWAITING_PAYMENT`). The submitted `amount_cents` must equal exactly the sum of `winning_bid_cents`, `buyer_fee_cents`, and any winner-side storage fee accrued so far on the sale's gate pass — which is zero when no gate pass exists yet or none has checked in. Any other amount is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. A clearing payment moves the sale to `PAID`, the settlement to `FINALIZED` (locking the seller's proceeds), and the vehicle to `RELEASED`.

Before payment, the seller can still unwind. Cancelling a sale requires its status to be `PENDING_APPROVAL` or `AWAITING_PAYMENT` (`ERR_SALE_NOT_CANCELLABLE`) and rolls everything back: the sale becomes `CANCELLED`; the settlement remains `DRAFT` with all money fields zeroed; the title record returns to `RECEIVED`; the vehicle's `title_brand` is restored to its prior value; the winning bid is released; and the vehicle returns to `SALE_READY`. Separately, a seller may cancel a vehicle outright at any point before it sells — from `ASSIGNED`, `AWAITING_CONDITION`, `SALE_READY`, `LISTED`, or `LIVE`, with any other state rejected as `ERR_VEHICLE_NOT_CANCELLABLE`. Cancelling a `LISTED` vehicle auto-cancels its queued auction item; cancelling a `LIVE` vehicle cancels the live item and releases every winning bid on it, and if that leaves the auction with no queued or live items, the auction completes automatically.

### 3.6. Money: Buyer Premium, Seller Settlement, and Dual-Side Storage

The buyer premium is a **marginal tiered premium over the hammer price**, computed at sale creation (on hammer close for `PURE` and `MINIMUM_BID`, on seller approval for `ON_APPROVAL`). The first 500000 cents of the hammer price are charged at 12%; the portion from 500000 up to (but not including) 2000000 cents is charged at 9%; any portion from 2000000 cents upward is charged at 6%. The pinned evaluation order is to compute each tier's portion in whole cents, round that tier's contribution half-up to whole cents **per tier**, and then sum the three rounded contributions. The alternative — summing the unrounded tier contributions and rounding once at the end — is a forbidden variant that can differ from the pinned result by up to two cents; implementations must round per tier.

The seller settlement is computed once, when the sale becomes `AWAITING_PAYMENT`, and its five steps evaluate in pinned order even though the dependency looks circular (the storage term keys off the sale day, which is the same transition that creates the settlement). First, `gross_proceeds_cents` is the hammer price. Second, `seller_fee_cents` is selected by the seller's `fee_schedule`: under `STANDARD` it is the greater of 2500 cents and 10 percent of the gross rounded half-up, plus a fixed 5000-cent title fee; under `VOLUME` it is the greater of 1500 cents and 7.5 percent of the gross rounded half-up, plus the same fixed 5000-cent title fee. The fixed title fee is never part of the floor comparison — it is added afterward. Third, `storage_recovery_cents` is the seller-side storage fee: the whole calendar days between the vehicle's `received_at` date and the sale-day UTC date, minus a seller free allowance of seven days (an allowance independent of the yard's winner-side `free_storage_days`), floored at zero, times the yard's `daily_storage_rate_cents`. Fourth, `title_late_penalty_cents` is a flat 15000 cents when the title record's acquisition exceeded the thirty-day SLA measured from `assigned_at` — exactly thirty days is not late — and zero otherwise. Fifth, `net_proceeds_cents` is the gross minus the seller fee, minus the storage recovery, minus the title late penalty; negative nets are legal and are persisted as computed. The settlement then advances `DRAFT → FINALIZED` when the buyer's payment clears, and `FINALIZED → PAID` when load-out completes.

Storage fees are charged to two different parties over two different windows against the **same** yard rate — the winner-side and seller-side variants share the day-granule rule of §2.6 but nothing else. On the winner side, at gate-pass check-in, the free allowance is the yard's `free_storage_days` counted from the UTC date of the sale day (the close, or the approval for on-approval sales); the chargeable days are the days between that sale date and the check-in date minus the allowance, floored at zero, and the fee is that count times `daily_storage_rate_cents`. On the seller side, as described above, the window runs from `received_at` to the sale day with a seven-day allowance.

### 3.7. Buyer Eligibility: Tiers, State Licenses, and Export Gating

Every bid is gated by the buyer's **effective tier**, evaluated against the state where the vehicle physically sits — the yard's `state_code`, never the member's `home_state`. The base tiers alone cover only `STANDARD` lots: `BASIC`, `PREMIER`, and `BUSINESS` members may all bid on standard lots. Coverage of restricted lots comes from licenses. A license is attached to a member with the issuing `state_code`, a `license_type` of `DEALER`, `DISMANTLER`, or `SALVAGE_BROKER`, and an `expires_on` date; it begins `ACTIVE` and may later be `REVOKED`. A license upgrades the effective tier only when it is `ACTIVE`, belongs to the member, its `state_code` matches the yard's state, and it has not expired — expiry is date-granular, and a license whose `expires_on` equals the current UTC date of the logical clock is still valid on that date. A `DEALER` license adds coverage of `DEALER_ONLY` lots; a `DISMANTLER` license adds `DISMANTLER_ONLY` lots; a `SALVAGE_BROKER` license adds both. A bid on a lot whose type is outside the bidder's effective tier is rejected with `ERR_LICENSE_REQUIRED` — whether the license is missing, issued by the wrong state, revoked, or expired. `EXPORT_ONLY` lots are biddable by any tier, but only by members whose `country_code` is not `US`. A suspended member cannot bid at all (`ERR_MEMBER_SUSPENDED`).

The title record adds one further bid-time gate: when the vehicle's title transferability is `EXPORT_ONLY`, a bid from a US member is rejected with `ERR_TITLE_EXPORT_ONLY` — such a vehicle can only be won by an exporter. By contrast, a `NON_TRANSFERABLE` title does not block bids at all; it blocks the hammer from falling (`ERR_TITLE_NON_TRANSFERABLE` at close).

### 3.8. Load-Out: Gate Passes, Yard Slots, and Export Documents

Once a sale is `PAID`, the winner — or a `YardOperator` acting on the buyer's behalf — books load-out by issuing a gate pass for the sale with a `slot_start` and `slot_end`. Issuance requires the sale to be `PAID` (`ERR_SALE_NOT_PAID`) and that no other pass for the same sale is currently `ISSUED` or `CHECKED_IN` (`ERR_GATE_PASS_ALREADY_ACTIVE`). The slot window must satisfy two shape rules: the end must be strictly after the start, and the duration must not exceed eight hours; a window violating either is rejected with `ERR_SLOT_WINDOW_INVALID` (HTTP 400). Yard capacity is enforced against overlapping bookings: within the one-hour window containing the new slot's start, at the vehicle's yard, there must be fewer than four other passes in `ISSUED` or `CHECKED_IN` status whose half-open intervals (start inclusive, end exclusive — touching boundaries do not overlap) intersect the new slot; the booking that would make five overlapping passes is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`. The same capacity rule is re-checked at check-in. A new pass begins `ISSUED` with `storage_fee_cents` at zero.

Arrival at the yard is recorded by check-in. Check-in requires the pass to be `ISSUED` (`ERR_GATE_PASS_INVALID_STATE`), the logical clock to be no later than the sale's `gate_pass_expires_at` — the 72-hour expiry is strict, so once the expiry instant has been reached or passed the check-in is rejected with `ERR_GATE_PASS_EXPIRED` and the pass is marked `EXPIRED` (a fresh pass may then be issued for the sale) — and the slot window to currently hold: the logical clock must fall between `slot_start` and `slot_end`, and the capacity rule above must still pass. Export compliance is checked here as well: when the winner's `country_code` is not `US`, a `VERIFIED` export document must exist for the sale, else `ERR_EXPORT_DOCUMENT_REQUIRED`. At a successful check-in, the winner-side storage fee is computed into `storage_fee_cents` per §3.6 and the pass becomes `CHECKED_IN`. Completion — the vehicle physically leaving — requires the pass to be `CHECKED_IN` (`ERR_GATE_PASS_INVALID_STATE`) and finishes the cycle in one bundle: the pass becomes `COMPLETED`, the vehicle becomes `LOADED_OUT`, and the settlement becomes `PAID`.

Export paperwork follows its own small lifecycle. A document is submitted for a sale by the winning buyer (or a `PlatformAdmin`) with a `document_type` of `BILL_OF_LADING`, `EXPORT_DECLARATION`, or `CUSTOMS_MANIFEST` and a `destination_country`; the destination must equal the winning member's `country_code`, else `ERR_EXPORT_DOC_COUNTRY_MISMATCH` (HTTP 422). The document begins `SUBMITTED`; a `PlatformAdmin` then verifies or rejects it, each action permitted only from `SUBMITTED` (`ERR_EXPORT_DOC_INVALID_STATE`), moving it to `VERIFIED` or `REJECTED`. Only a `VERIFIED` document satisfies the load-out gate.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a distinct resource to a collection return `201 Created`; operations that modify an existing resource return `200 OK`. The single test-driving capability, setting the logical clock, returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/salvage-auction/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/salvage-auction/yards` | Create a yard | PlatformAdmin |
| GET | `/salvage-auction/yards` | List yards | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/yards/{id}` | Get a yard | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| POST | `/salvage-auction/sellers` | Create a seller (insurer) | PlatformAdmin |
| GET | `/salvage-auction/sellers` | List sellers | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/sellers/{id}` | Get a seller | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| POST | `/salvage-auction/members` | Register a buyer member | PlatformAdmin |
| GET | `/salvage-auction/members` | List members | PlatformAdmin, Auctioneer, TitleClerk |
| GET | `/salvage-auction/members/{id}` | Get a member | PlatformAdmin, Auctioneer, TitleClerk, Buyer |
| POST | `/salvage-auction/members/{id}/licenses` | Attach a state-issued license to a member | PlatformAdmin, TitleClerk |
| GET | `/salvage-auction/members/{id}/licenses` | List a member's licenses | PlatformAdmin, Auctioneer, TitleClerk, Buyer |
| GET | `/salvage-auction/licenses/{id}` | Get a license | PlatformAdmin, Auctioneer, TitleClerk, Buyer |
| POST | `/salvage-auction/vehicles` | Assign a vehicle to a yard | SellerAgent |
| GET | `/salvage-auction/vehicles` | List vehicles | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/vehicles/{id}` | Get a vehicle | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| POST | `/salvage-auction/vehicles/{id}/images` | Attach one condition image | YardOperator |
| POST | `/salvage-auction/vehicles/{id}/condition` | Submit or revise the condition report | YardOperator |
| POST | `/salvage-auction/vehicles/{id}/mark-ready` | Advance the vehicle to sale-ready (OCC-guarded) | YardOperator |
| POST | `/salvage-auction/vehicles/{id}/cancel` | Seller cancels a pre-sale vehicle | SellerAgent |
| POST | `/salvage-auction/vehicles/{id}/title` | Record title acquisition for a vehicle | TitleClerk |
| GET | `/salvage-auction/vehicles/{id}/title` | Get the title record for a vehicle | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/titles/{id}` | Get a title record by id | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, TitleClerk |
| POST | `/salvage-auction/auctions` | Schedule an auction event | Auctioneer |
| GET | `/salvage-auction/auctions` | List auctions | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/auctions/{id}` | Get an auction | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| POST | `/salvage-auction/auctions/{id}/start` | Open the auction and assign the running order | Auctioneer |
| POST | `/salvage-auction/auctions/{id}/items` | List a sale-ready vehicle into a scheduled auction | Auctioneer |
| GET | `/salvage-auction/auctions/{id}/items` | List items of an auction | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/vehicles/{id}/auction-items` | List auction items for a vehicle | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/auction-items/{id}` | Get an auction item | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| POST | `/salvage-auction/auctions/{id}/items/{itemId}/open-lot` | Open the next lot in sequence | Auctioneer |
| POST | `/salvage-auction/auctions/{id}/items/{itemId}/close-lot` | Close the live lot and produce a sale | Auctioneer |
| POST | `/salvage-auction/auctions/{id}/items/{itemId}/cancel` | Cancel a queued item | Auctioneer |
| POST | `/salvage-auction/bids` | Place a preliminary or live bid | Buyer |
| GET | `/salvage-auction/bids` | List bids | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/bids/{id}` | Get a bid | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/sales` | List sales | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/sales/{id}` | Get a sale | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| POST | `/salvage-auction/sales/{id}/approve` | Seller approves an on-approval sale | SellerAgent |
| POST | `/salvage-auction/sales/{id}/reject-offer` | Seller rejects an on-approval high bid | SellerAgent |
| POST | `/salvage-auction/sales/{id}/cancel` | Seller unwinds a sale before payment | SellerAgent |
| POST | `/salvage-auction/sales/{id}/payments` | Buyer pays hammer plus buyer fee plus accrued storage | Buyer |
| POST | `/salvage-auction/sales/{id}/gate-passes` | Issue a gate pass with a load-out slot | Buyer, YardOperator |
| GET | `/salvage-auction/sales/{id}/gate-passes` | List gate passes for a sale | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/gate-passes/{id}` | Get a gate pass | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| POST | `/salvage-auction/gate-passes/{id}/check-in` | Check in at the yard inside the slot window | YardOperator |
| POST | `/salvage-auction/gate-passes/{id}/complete` | Complete load-out | YardOperator |
| GET | `/salvage-auction/sales/{id}/settlement` | Get the settlement for a sale | PlatformAdmin, Auctioneer, SellerAgent, TitleClerk |
| GET | `/salvage-auction/settlements` | List settlements, filterable by seller | PlatformAdmin, Auctioneer, SellerAgent, TitleClerk |
| GET | `/salvage-auction/settlements/{id}` | Get a settlement by id | PlatformAdmin, Auctioneer, SellerAgent, TitleClerk |
| POST | `/salvage-auction/sales/{id}/export-documents` | Submit an export document for a sale | Buyer, PlatformAdmin |
| GET | `/salvage-auction/sales/{id}/export-documents` | List export documents for a sale | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| GET | `/salvage-auction/export-documents/{id}` | Get an export document | PlatformAdmin, YardOperator, Auctioneer, SellerAgent, Buyer, TitleClerk |
| POST | `/salvage-auction/export-documents/{id}/verify` | Verify a submitted export document | PlatformAdmin |
| POST | `/salvage-auction/export-documents/{id}/reject` | Reject a submitted export document | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_YARD_NOT_FOUND` | 404 Not Found |
| `ERR_SELLER_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_LICENSE_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_TITLE_NOT_FOUND` | 404 Not Found |
| `ERR_AUCTION_NOT_FOUND` | 404 Not Found |
| `ERR_AUCTION_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_SALE_NOT_FOUND` | 404 Not Found |
| `ERR_GATE_PASS_NOT_FOUND` | 404 Not Found |
| `ERR_EXPORT_DOC_NOT_FOUND` | 404 Not Found |
| `ERR_EMAIL_TAKEN` | 409 Conflict |
| `ERR_VIN_DUPLICATE` | 409 Conflict |
| `ERR_TITLE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_VEHICLE_ALREADY_LISTED` | 409 Conflict |
| `ERR_SELLER_SUSPENDED` | 409 Conflict |
| `ERR_YARD_CLOSED` | 409 Conflict |
| `ERR_VEHICLE_INVALID_STATE` | 409 Conflict |
| `ERR_VEHICLE_NOT_IMAGE_READY` | 409 Conflict |
| `ERR_VEHICLE_INCOMPLETE_CONDITION` | 409 Conflict |
| `ERR_VEHICLE_NOT_SALE_READY` | 409 Conflict |
| `ERR_VEHICLE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_TITLE_NOT_RECEIVED` | 409 Conflict |
| `ERR_TITLE_NON_TRANSFERABLE` | 409 Conflict |
| `ERR_TITLE_EXPORT_ONLY` | 403 Forbidden |
| `ERR_AUCTION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_AUCTION_NOT_LIVE` | 409 Conflict |
| `ERR_AUCTION_NOT_YET_STARTED` | 409 Conflict |
| `ERR_AUCTION_EMPTY` | 409 Conflict |
| `ERR_AUCTION_ITEM_NOT_QUEUED` | 409 Conflict |
| `ERR_AUCTION_ITEM_NOT_LIVE` | 409 Conflict |
| `ERR_AUCTION_ITEM_ALREADY_LIVE` | 409 Conflict |
| `ERR_AUCTION_ITEM_OUT_OF_ORDER` | 409 Conflict |
| `ERR_NO_BIDS` | 409 Conflict |
| `ERR_RESERVE_NOT_MET` | 409 Conflict |
| `ERR_LICENSE_REQUIRED` | 403 Forbidden |
| `ERR_MEMBER_SUSPENDED` | 403 Forbidden |
| `ERR_BID_INCREMENT_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_BID_SELF_OUTBID` | 422 Unprocessable Entity |
| `ERR_SALE_NOT_PENDING_APPROVAL` | 409 Conflict |
| `ERR_SALE_NOT_AWAITING_PAYMENT` | 409 Conflict |
| `ERR_SALE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SELLER_MISMATCH` | 403 Forbidden |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SALE_NOT_PAID` | 409 Conflict |
| `ERR_GATE_PASS_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_GATE_PASS_INVALID_STATE` | 409 Conflict |
| `ERR_GATE_PASS_EXPIRED` | 409 Conflict |
| `ERR_SLOT_WINDOW_INVALID` | 400 Bad Request |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_EXPORT_DOCUMENT_REQUIRED` | 409 Conflict |
| `ERR_EXPORT_DOC_INVALID_STATE` | 409 Conflict |
| `ERR_EXPORT_DOC_COUNTRY_MISMATCH` | 422 Unprocessable Entity |
