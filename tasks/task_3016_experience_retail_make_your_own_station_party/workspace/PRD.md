# Experience Retail Workshop API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Experience Retail Workshop API, the back-of-house and guest-facing system for a build-your-own stuffed animal retailer operating guided in-store workshops. A visit moves a guest through a fixed sequence of physical stations — shell selection, stuffing, sound insertion, bathing and grooming, and dressing — and the API must model that sequencing faithfully: it tracks which station a session occupies, decrements stuffing fiber and sound-chip stock as they are consumed, mints a stuffed-animal identity at the moment a shell is committed, and prices the finished animal as options accumulate.

Beyond the core build flow, the system carries the retailer's surrounding commercial machinery. Birthday parties are reserved as two-hour appointment blocks with per-guest package tiers, a deposit structure that differentiates the top tier from the rest, host staffing for staff-hosted parties, and a settlement step that converts attendance marks into a final bill. Licensed character collection drops impose per-customer purchase limits and a finite unit pool that claims and releases as sessions advance or abandon. Online build-and-ship orders are assembled in-store through the same workshop pipeline and handed to a carrier, feeding a consignment settlement report. Gift cards, stuffed-animal registries with linked-tender payment, birth-certificate personalization, and a lost-toy recovery service round out the guest relationship.

The API is exercised against a logical clock rather than wall-clock time, so every temporal rule — booking lead times, drop purchase windows, auto-confirmation of parties, consignment windows — is deterministic. All state transitions, calculations, and access rules described here are normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly four roles: `Customer`, `WorkshopAssociate`, `PartyHost`, and `StoreManager`. A request missing `X-User-Role`, carrying an undeclared role value, or — for an entity-backed role — missing `X-User-ID` is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED`.

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a customer — a workshop session, a party reservation, a stuffed animal, a registry, a gift-card redemption — compare the resource's customer foreign key to `X-User-ID`. When `X-User-Role` is `WorkshopAssociate` or `PartyHost`, `X-User-ID` is the `id` of the acting `StaffMember` entity, and any staff-referencing check (such as host reservation visibility) compares against that identifier. When `X-User-Role` is `StoreManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints accept the query parameters `limit` and `offset`. When `limit` is not supplied it defaults to 10, and it is bounded between a minimum of 1 and a maximum of 100. `offset` defaults to 0 and identifies how many items to skip. Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. The Logical Clock

The server keeps a logical clock that governs every temporal rule in this document: booking lead time, collection-drop windows, party auto-confirmation, finalize timing, and consignment windows all read this clock and never the wall clock. At server startup, before any adjustment, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `StoreManager` may advance it by supplying `to_iso8601`; the response echoes the new position as `current_utc`. Advancing the clock is also the trigger that evaluates time-based automatic transitions — in particular the confirmation of deposit-paid parties once the clock crosses the twenty-four-hours-before-party threshold. Rejections caused by temporal rules carry `ERR_OUTSIDE_TIME_WINDOW`.

### 2.5. Common Resource Properties

All primary resources in this API — stores, customers, staff members, stations, plush models, consumables, collection drops, workshop sessions, stuffed animals, party reservations, party guests, appointment blocks, build-and-ship orders, gift cards, and registries — share a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation, including state transitions, payment application, linking operations, and restocks. Automatic transitions triggered by the logical clock or by a parent lifecycle event mutate the affected resource the same way: its `updated_at` refreshes and its `version` increments.

### 2.6. Monetary Precision

All monetary values are integer cents; there is no fractional-cent arithmetic anywhere in the system. Where a percentage is applied (the party service charge and the consignment commission), the result is rounded half up to the nearest whole cent, and — critically for party billing — rounding is applied per guest line before any summation. The rejected alternative is summing raw amounts and rounding once at the end.

### 2.7. Validation Ordering

When an endpoint performs several checks, they are evaluated in a fixed priority order, and the first failing check determines the rejection. Authentication (§2.1) comes first, followed by role authorization, then existence of path parameters validated left-to-right, then existence of body-referenced resources. Only after all references resolve does the server evaluate whether the target resource is in a state that permits the requested action (`ERR_INVALID_STATE`). Temporal rules — lead time, drop windows, finalize timing — come next (`ERR_OUTSIDE_TIME_WINDOW`), followed by licensed-drop safety rails (`ERR_DROP_LIMIT_REACHED`), then capacity and scheduling constraints such as station occupancy and host availability, then cross-entity referential integrity (including gift-card linkage and party guest counts), then funds and stock sufficiency, and finally field-level shape validation (`ERR_VALIDATION`). An earlier failure masks all later ones: a request that fails the drop-window check, for example, never surfaces a stock error even if stock is also short.

### 2.8. Nested Resource Retrieval

For any endpoint whose path contains multiple resource identifiers, the server validates existence sequentially from left to right and rejects immediately with `ERR_NOT_FOUND` at the first identifier that does not resolve. A request aimed at a list under a non-existent store fails on the store identifier before any sub-resource is examined. Body-referenced identifiers — the `store_id`, `customer_id`, `plush_model_id`, `collection_drop_id`, `gift_card_id`, or `registry_id` carried in a payload — are likewise checked for existence and rejected with `ERR_NOT_FOUND` when absent.

### 2.9. Optimistic Concurrency Control

One endpoint is guarded by optimistic concurrency control: rescheduling a party reservation. The request must carry `expected_party_version`, a non-optional field holding the client-observed `version` of the reservation. If another writer has advanced the reservation's version since the client last read it, the value no longer matches the current `version` and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; all other mutations proceed without an OCC check.

### 2.10. Half-Open Intervals and Touching Boundaries

Every temporal and occupancy window in the system is a half-open interval: the start instant is included, the end instant is excluded. Two intervals that merely touch — one ending exactly when the other begins — do not overlap. This convention governs collection-drop purchase windows, appointment-block room overlap checks, party-host double-booking checks, station occupancy windows, and the consignment settlement window alike.

## 3. Business Logic & Workflows

### 3.1. Store Setup: Catalog, Stations, Staff, and Stock

A `StoreManager` onboards a store by registering it with a `name` and a `party_room_count`, the number of party rooms the location operates; each store must have at least one party room, and the room count later bounds how many appointment blocks may overlap. Within a store, the manager creates workshop stations, each carrying a `store_id`, a `station_type` of `SELECT`, `STUFF`, `SOUND`, `BATHE`, or `DRESS`, and a `capacity` of at least one — the maximum number of workshop sessions the station may serve at once. Staff are hired per store with a `display_name` and a `role_title` drawn from `ASSOCIATE`, `PARTY_HOST`, or `MANAGER`; only staff whose `role_title` is `PARTY_HOST` are eligible to be reserved as party hosts.

The product catalog is a set of plush models. Before anything else can happen, a guest registers as a customer with an `email`, unique across all customers, and a `full_name`. A `StoreManager` registers each model with a `name` (for example, "Celestial Dragon"), a `sku` that must be unique across all plush models, a `base_price_cents` of zero or more representing the retail price of the unstuffed shell, an `is_licensed` flag marking membership in a licensed collection, a strictly positive `required_stuffing_grams` describing how much fiber one unit consumes at the stuffing step, and a `sound_chip_compatible` flag declaring whether the model accepts a sound insert.

In-store production runs on a consumables ledger. For each store, a manager creates ledger rows with a `consumable_type` of `STUFFING_FIBER` (quantities measured in grams) or `SOUND_CHIP` (quantities measured in units) and an opening `initial_qty` of zero or more. The row's `on_hand_qty` starts at `initial_qty`, is decremented as workshop sessions and build-and-ship assemblies consume stock, and is incremented when a manager records a restock with a `quantity`. On-hand quantity may never go negative. The governing invariant for the stuffing ledger is that the opening quantity plus all restocks, minus fiber consumed by sessions, plus fiber restored by abandonments, always equals `on_hand_qty`; restock events apply in chronological order by `created_at`, with ties broken by creation timestamp ascending and then request order. A sound-chip price of 1500 cents applies whenever a chip is installed during a build.

### 3.2. Licensed Collection Drops

Licensed models are sold through time-boxed collection drops. A `StoreManager` creates a drop with a `name`, the `plush_model_id` of the licensed model it offers — the referenced model's `is_licensed` must be true — a `drop_start` and `drop_end` defining the half-open purchase window, a `per_customer_limit` of at least one bounding how many units of the drop's model a single customer may claim across all of their workshops, and a `total_units` pool size of at least one. The drop tracks a running `units_claimed` counter, starting at zero, bounded between zero and `total_units`.

Claiming happens when a workshop session for a licensed model advances past shell selection, and release happens when such a session is abandoned before payment. The guard rails reject claims with `ERR_DROP_LIMIT_REACHED` in two situations: when the customer has already selected `per_customer_limit` units of the drop's model across their non-terminal sessions, and when `units_claimed` has reached `total_units`. The window itself is enforced separately: a claim made when the current logical time falls before `drop_start` or at or after `drop_end` is rejected with `ERR_OUTSIDE_TIME_WINDOW`.

A session for a licensed model must carry a `collection_drop_id` referencing a drop whose model matches the selected plush model; a missing drop reference, or one pointing at a drop for a different model, is rejected with `ERR_REFERENTIAL_INTEGRITY`. Non-licensed models never carry a drop reference.

### 3.3. The Workshop Floor: From Shell Selection to Dressing

A `WorkshopAssociate` starts a walk-in workshop session by providing the `store_id`, `customer_id`, `plush_model_id`, and an `origin_type` of `WALK_IN`. Sessions with `origin_type` `PARTY` or `BUILD_SHIP` are never created through this entry point — they are spawned by their parent flows, carrying a `party_reservation_id` or `build_ship_order_id` respectively, while walk-ins carry neither. A new session begins in `SELECT` status, stamps `started_at` from the logical clock, and has no assigned station yet: `assigned_station_id` stays empty until the first advance.

Walk-in admission is capacity-gated. A session occupies its station across a half-open interval that begins fifteen minutes before the session start (the setup buffer) and extends forty-five minutes of session duration plus a further fifteen minutes (the teardown buffer) — a ninety-minute occupied span in total. The occupancy of a station at any instant is the count of non-terminal sessions at the same store whose occupied interval covers that instant, counting sessions that begin exactly when another ends as non-overlapping. If the relevant `SELECT`-type station pool at the store has every station at occupancy equal to `capacity`, the new session is rejected with `ERR_STATION_AT_CAPACITY`.

Advancement drives the build forward one station step at a time: `SELECT` → `SELECTED` → `STUFFED` → `SOUNDED` → `BATHED` → `DRESSED`. Each advance is performed by a `WorkshopAssociate`, re-points `assigned_station_id` to the station chosen for the next stage, and increments the session's `version`. An advance attempted from a state with no outgoing transition — such as any advance on a terminal session — is rejected with `ERR_INVALID_STATE`.

Station selection for the next stage considers every station at the session's store whose `station_type` matches that stage and whose current occupancy is strictly below its `capacity`. Among candidates, the station with the lowest current occupancy wins; ties break to the station created earliest, and the entity identifier is never consulted as a tie-breaker. When no candidate has spare capacity, the advance fails with `ERR_STATION_AT_CAPACITY`.

The first advance, from `SELECT` to `SELECTED`, is the commitment step. For licensed models it is where the drop window, per-customer limit, and total-units checks all fire — in the global validation order, the temporal window is evaluated first, then the drop-limit rails — and it is where `units_claimed` on the drop increments by one. Regardless of licensing, this advance mints a `StuffedAnimal` in `IN_PROGRESS` status and records it as the session's `stuffed_animal_id`; the animal inherits the session's `customer_id` and `plush_model_id` and remembers its `origin_workshop_session_id`. The session's `total_price_cents` is quoted at this moment as the model's `base_price_cents`.

From `SELECTED` to `STUFFED`, the stuffing station consumes fiber: the store's `STUFFING_FIBER` ledger must hold at least `required_stuffing_grams` on hand, otherwise the advance is rejected with `ERR_INSUFFICIENT_STOCK`. On success the ledger's `on_hand_qty` decreases by exactly `required_stuffing_grams` and the session records the same amount as `stuffing_grams_used` (zero until this point). Associates can observe the depletion through the consumables listing and trigger restocks accordingly.

From `STUFFED` to `SOUNDED`, behavior forks on the model's `sound_chip_compatible` flag. A compatible model mandates a sound insert: the store's `SOUND_CHIP` ledger must hold at least one unit on hand, else `ERR_INSUFFICIENT_STOCK`; on success one chip is decremented, `sound_chip_used` becomes true, and the chip price of 1500 cents is added to `total_price_cents`. An incompatible model passes through the sound step as a no-op — `sound_chip_used` stays false and the price is unchanged. The steps from `SOUNDED` to `BATHED` and from `BATHED` to `DRESSED` consume no stock; the final advance to `DRESSED` also releases the session's station assignment, freeing its occupancy for other builds.

### 3.4. Abandonment and Compensating Restoration

A `WorkshopAssociate` may abandon any non-terminal session, moving it to `ABANDONED`. Abandonment always releases the session's station assignment and increments its `version`, and the compensating effects scale with how far the build progressed.

From `SELECT`, abandonment merely frees the station. From `SELECTED`, it additionally decrements `units_claimed` on the associated drop by one when the model is licensed, restoring availability for other customers' claims. From `STUFFED`, the consumed fiber comes back: the store's `STUFFING_FIBER` ledger is credited `stuffing_grams_used`, alongside the drop release when licensed. From `SOUNDED`, both the fiber and one sound-chip unit are restored. From `BATHED`, the fiber is restored and one chip is restored only when `sound_chip_used` is true for the session — a no-op sound step leaves nothing to give back. Abandonment from `DRESSED` restores consumables exactly as from `BATHED`, and additionally propagates to parent flows: a party-origin session marks its linked guest `NO_SHOW`, while a build-ship-origin session cancels its linked order, moving it to `CANCELLED`.

### 3.5. Payment, Tenders, and the Completed Animal

Payment is the terminal act of a build. A session in `DRESSED` is paid by its `Customer`, who submits `payment_amount_cents` and a `pay_tender` of `CASH`, `GIFT_CARD`, or `GIFT_CARD_LINKED`; a session in any other state is rejected with `ERR_INVALID_STATE`. The submitted amount must equal the session's `total_price_cents` exactly — any mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`.

With `CASH`, no further instrument checks apply. With `GIFT_CARD`, the request carries a `gift_card_id`; the referenced card must be `ACTIVE` and hold a `balance_cents` of at least the payment amount, or the payment is rejected with `ERR_GIFT_CARD_INSUFFICIENT`. With `GIFT_CARD_LINKED`, the request carries both `gift_card_id` and `registry_id`; the named registry must contain the gift card in its `linked_gift_card_ids` **and** the session's stuffed animal in its `linked_animal_ids`, and the card's balance must cover the full payment amount — split tender is not supported. A linkage failure is rejected with `ERR_GIFT_CARD_NOT_LINKED`, while an insufficient or non-`ACTIVE` card is rejected with `ERR_GIFT_CARD_INSUFFICIENT`. In the global validation order, linkage (a referential-integrity check) is evaluated before balance sufficiency (a fiscal check), so a tender that fails both surfaces `ERR_GIFT_CARD_NOT_LINKED`.

A successful payment moves the session to `PAID` and completes the minted animal, whose status becomes `COMPLETED` — completion is what makes an animal eligible for registry linking. For gift-card tenders, the card's `balance_cents` decreases by the payment amount; a card whose balance reaches exactly zero transitions from `ACTIVE` to `EXHAUSTED`. When the paid session has `origin_type` `PARTY`, its linked guest is marked `ATTENDED`; when it has `origin_type` `BUILD_SHIP`, the linked order moves to `READY_FOR_PICKUP`, which is the precondition for carrier handoff.

### 3.6. Party Reservations: Quote, Deposit, and Booking

A `Customer` books a party by quoting a reservation with the `store_id`, their `customer_id`, a `party_start` that must fall on a whole hour, a `duration_minutes` that must be exactly 120, a `guest_count` between 6 and 20 inclusive, a `package_tier` of `BASIC`, `CELEBRATION`, or `ULTIMATE`, and a `staffing_mode` of `STAFF_HOSTED` or `SELF_GUIDED`. A reservation is born in `QUOTED` status with `final_amount_due_cents` at zero and `paid_amount_cents` at zero, and its `deposit_amount_cents` is computed at quote time.

The deposit is tier-sensitive. For `ULTIMATE` parties the deposit is the greater of two values: the guest count times 1000 cents per guest, or a floor of 20000 cents. For `BASIC` and `CELEBRATION` parties the deposit is a flat 10000 cents regardless of headcount. All deposit arithmetic is integer cents with no rounding.

Paying the deposit converts `QUOTED` to `DEPOSIT_PAID`. The submitted `payment_amount_cents` must equal `deposit_amount_cents` exactly (`ERR_PAYMENT_AMOUNT_MISMATCH`), and the deposit is credited into `paid_amount_cents`. Three further conditions gate the deposit. First, lead time: the deposit must be paid at least 72 hours before `party_start`, otherwise `ERR_OUTSIDE_TIME_WINDOW`. Second, room availability: the count of `ACTIVE` appointment blocks at the store overlapping the half-open interval from `party_start` to `party_start` plus 120 minutes must be below the store's `party_room_count`, with touching endpoints not counted as overlapping. Third, staffing: for a `STAFF_HOSTED` party the host selector must find a candidate — a `StaffMember` at the same store whose `role_title` is `PARTY_HOST` and who holds no `ACTIVE` block overlapping the party interval (touching endpoints permitted) — ranked by fewest `ACTIVE` reserved blocks ascending, ties broken by earliest creation; an empty pool rejects the deposit with `ERR_HOST_UNAVAILABLE`.

On success, the booking creates an `AppointmentBlock` in `ACTIVE` status holding the reservation's `store_id` and `party_reservation_id`, with `block_start` copied from `party_start` and `block_end` set to `block_start` plus the 120-minute duration. For `STAFF_HOSTED` parties the block's `reserved_host_id` records the selected host — that reservation is precisely what makes the host ineligible for a later overlapping booking, surfacing `ERR_HOST_UNAVAILABLE` on the competing request; `SELF_GUIDED` parties leave `reserved_host_id` empty.

A customer may reschedule a quoted reservation by supplying a `new_party_start` — which must also fall on a whole hour — together with the OCC guard described in §2.9: `expected_party_version` must match the reservation's current `version`, or the request is rejected with `ERR_STALE_VERSION`. Rescheduling re-runs the room-overlap and host-selection checks against the new interval, updates the appointment block's times, and increments the reservation's `version`.

### 3.7. Party Guests, Auto-Confirmation, Finalization, and Cancellation

Guests are added to a reservation by the booking `Customer`, each with a `party_reservation_id` and a `guest_name`, beginning life in `INVITED` status. Confirming a guest requires the reservation to be in `QUOTED` or `DEPOSIT_PAID` and the count of `CONFIRMED` guests to be below the reservation's `guest_count`; exceeding the booked headcount is rejected with `ERR_PARTY_GUEST_LIMIT`. An invited guest may be cancelled outright, moving to `CANCELLED`; a confirmed guest may be cancelled only while the reservation is still in `QUOTED` or `DEPOSIT_PAID` — once the reservation is `CONFIRMED`, a guest can only resolve to `ATTENDED` or `NO_SHOW`.

Twenty-four hours before `party_start`, the system auto-transitions the reservation from `DEPOSIT_PAID` to `CONFIRMED`; the transition is evaluated when the logical clock crosses the threshold. At that moment, for each guest still in `CONFIRMED` status, the system creates their party-origin workshop session in `SELECT` and records it as the guest's `workshop_session_id`. From that point each guest's build is an ordinary workshop session subject to the usual station-capacity and drop-limit rules at advance time, and its payment marks the guest `ATTENDED` while its abandonment marks the guest `NO_SHOW`.

After the block ends, a `StoreManager` finalizes the party. Finalization requires the logical clock to have reached `party_start` plus the 120-minute duration (earlier attempts are rejected with `ERR_OUTSIDE_TIME_WINDOW`) and every guest in `CONFIRMED` status to have resolved to either `ATTENDED` (their session was paid) or `NO_SHOW` (their session was abandoned or cancelled); finalizing a reservation not in `CONFIRMED` status, or with unresolved guests, is rejected with `ERR_INVALID_STATE`. The final bill is computed per guest line: each billable guest — those in `CONFIRMED` or `ATTENDED` status — is charged the tier's per-guest price (1899 cents for `BASIC`, 4299 cents for `CELEBRATION`, 7999 cents for `ULTIMATE`) plus a 15 percent service charge rounded half up to the nearest cent on that line. The per-line amounts are then summed into a subtotal, and the previously collected `deposit_amount_cents` is subtracted to produce `final_amount_due_cents`. If the deposit exceeds the subtotal, the result is clamped to zero and the excess deposit is forfeited, never refunded. The customer settles the bill by paying the balance: the submitted `payment_amount_cents` is credited into `paid_amount_cents`. A successful finalize moves the reservation to `COMPLETED`.

Cancelling a reservation releases its appointment block — the block's status becomes `RELEASED`, freeing the room slot and any reserved host, which is what allows a later overlapping booking to succeed. Cancelling from `QUOTED` involves no money. Cancelling from `DEPOSIT_PAID` or `CONFIRMED` computes a deposit refund in a tier-insensitive, attendance-sensitive mode: if cancellation happens inside the 72-hour lead window before `party_start`, the refund is zero; otherwise the refund is 1000 cents multiplied by the smaller of the guest count booked at quote time and the honored count, where the honored count is the number of the reservation's guests whose status is not `NO_SHOW` at cancel time. The refund is recorded as a negative adjustment to `paid_amount_cents`. Cancelling a `CONFIRMED` party additionally cascades: every non-terminal party-origin workshop session is abandoned, and their guests are marked `NO_SHOW`. All cancellation paths end in `CANCELLED`.

### 3.8. Build-and-Ship Orders and Consignment Settlement

An online build-and-ship order lets a `Customer` have an animal assembled at a store and shipped to a recipient. Placing one takes the fulfilling `store_id`, the ordering `customer_id`, the `plush_model_id`, a `sound_chip_requested` flag for the optional sound insert, and the ship-to `recipient_name`; the order begins in `PLACED` status.

A `WorkshopAssociate` begins assembly when stock suffices: the store's stuffing-fiber ledger must hold at least the model's `required_stuffing_grams`, and if `sound_chip_requested` is true, at least one sound-chip unit, else the request is rejected with `ERR_INSUFFICIENT_STOCK`. Starting assembly moves the order to `IN_ASSEMBLY` and creates a build-ship-origin workshop session in `SELECT`, recorded as the order's `workshop_session_id`; that session's own advances consume the same store consumables ledger as any walk-in build. When the session is eventually paid, the order auto-transitions from `IN_ASSEMBLY` to `READY_FOR_PICKUP`. Handoff to the carrier is performed by an associate supplying a `carrier_code` and a `tracking_number`, both required; the order moves to `HANDED_TO_CARRIER` and stamps `handed_over_at` from the logical clock.

A customer may cancel an order from `PLACED` outright. From `IN_ASSEMBLY`, cancellation is allowed only while the linked session has not yet reached `DRESSED` — that is, while it sits anywhere from `SELECT` through `BATHED`; the cancellation abandons the linked session, which restores its consumed consumables per the abandonment rules of §3.4. An order whose session has reached `DRESSED` or beyond, or which is already `READY_FOR_PICKUP`, can no longer be cancelled (`ERR_INVALID_STATE`).

Store managers run a consignment settlement over a supplied half-open window, providing `window_start` and `window_end`. Eligible orders are the store's build-and-ship orders in `HANDED_TO_CARRIER` status whose `handed_over_at` falls inside the window — start inclusive, end exclusive. The settlement evaluates three figures in a pinned order, each depending on the previous: first `gmv_cents`, the sum of the eligible orders' workshop session `total_price_cents` (session totals are already per-line rounded, so this summation introduces no new rounding); then `commission_cents`, the gross merchandise value multiplied by 18 percent and rounded half up to the nearest cent; then `store_bonus_cents`, the commission divided by the number of eligible orders — with a zero-eligible count treated as one for the division — rounded half up to the nearest cent. The response also reports `eligible_order_count`.

### 3.9. Gift Cards, Registries, Birth Certificates, and Lost-Toy Recovery

A `StoreManager` issues a gift card with a `code` unique across all gift cards and a strictly positive `initial_balance_cents`; the card's `balance_cents` starts at the issued amount and its status is `ACTIVE`. Redemption at payment time is the only operation that reduces the balance, and a card driven to zero becomes `EXHAUSTED`. A manager may also disable a card, moving it to `DISABLED`; neither an exhausted nor a disabled card can fund a payment. Balance arithmetic never lets `balance_cents` go negative.

A registry belongs to one `Customer` — created with the owner's `customer_id` and a display `name` such as "Maya's Wish List" — and accumulates two link collections. Linking a stuffed animal adds its identifier to `linked_animal_ids`; only a `COMPLETED` animal owned by the registry's owner may be linked, and an animal may belong to at most one registry — attempting to link an animal already held by another registry, or one not owned by the registry owner, is rejected with `ERR_REFERENTIAL_INTEGRITY`. Linking a gift card adds its identifier to `linked_gift_card_ids`. Together these links are what enable the `GIFT_CARD_LINKED` tender described in §3.5 for the registry owner's future sessions: the card must be in the registry's card list and the session's animal in its animal list.

Birth-certificate personalization is available until the originating session is paid. The owning customer supplies `birth_cert_name` and `birth_cert_birth_date` — the latter a date string in year-month-day form — which are printed on the certificate; once the origin session reaches `PAID`, both fields are immutable and further personalization attempts are rejected with `ERR_REFERENTIAL_INTEGRITY`.

The lost-toy service applies to completed animals and is strictly owner-only: the acting customer's identity must match the animal's `customer_id`, otherwise the request is rejected with `ERR_UNAUTHORIZED` — and acting on an animal in the wrong state is rejected with `ERR_INVALID_STATE`. Reporting a `COMPLETED` animal lost moves it to `LOST_REPORTED`. From there the owner may mark it `RECOVERED` when the toy turns up, or cancel the lost report to return the animal to `COMPLETED`. `RECOVERED` is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or trigger a computation return `200 OK`. Request payloads, response shapes, side effects, and authorization nuances are defined in §2 and §3; the table below is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock | StoreManager |
| POST | `/stores` | Create a store | StoreManager |
| GET | `/stores/{id}` | Get a store | Customer, WorkshopAssociate, PartyHost, StoreManager |
| GET | `/stores/{id}/staff` | List staff members of a store | WorkshopAssociate, StoreManager |
| GET | `/stores/{id}/stations` | List stations of a store | WorkshopAssociate, StoreManager |
| GET | `/stores/{id}/workshops` | List workshop sessions at a store (optional `status` filter) | WorkshopAssociate, StoreManager |
| GET | `/stores/{id}/parties` | List party reservations booked at a store | PartyHost, StoreManager |
| GET | `/stores/{id}/appointment-blocks` | List appointment blocks held at a store | PartyHost, StoreManager |
| GET | `/stores/{id}/consumables` | List consumable ledger rows for a store | WorkshopAssociate, StoreManager |
| GET | `/stores/{id}/build-ship-orders` | List build-and-ship orders fulfilled by a store (optional `status` filter) | WorkshopAssociate, StoreManager |
| POST | `/stores/{id}/consignments/run` | Compute the consignment settlement over a half-open handoff window | StoreManager |
| POST | `/staff` | Create a staff member | StoreManager |
| GET | `/staff/{id}` | Get a staff member | WorkshopAssociate, PartyHost, StoreManager |
| GET | `/staff/{id}/appointment-blocks` | List appointment blocks reserving this staff member as host | WorkshopAssociate, StoreManager |
| POST | `/stations` | Create a workshop station | StoreManager |
| GET | `/stations/{id}` | Get a station | WorkshopAssociate, StoreManager |
| GET | `/stations/{id}/workshops` | List workshop sessions currently assigned to a station | WorkshopAssociate, StoreManager |
| POST | `/plush-models` | Create a plush model | StoreManager |
| GET | `/plush-models/{id}` | Get a plush model | Customer, WorkshopAssociate, PartyHost, StoreManager |
| GET | `/plush-models/{id}/workshops` | List workshop sessions building this model | WorkshopAssociate, StoreManager |
| GET | `/plush-models/{id}/collection-drops` | List collection drops offering this model | Customer, WorkshopAssociate, StoreManager |
| GET | `/plush-models/{id}/build-ship-orders` | List build-and-ship orders for this model | WorkshopAssociate, StoreManager |
| GET | `/plush-models/{id}/animals` | List stuffed animals of this model | WorkshopAssociate, StoreManager |
| POST | `/consumables` | Create a consumable ledger row for a store | StoreManager |
| GET | `/consumables/{id}` | Get a consumable row | WorkshopAssociate, StoreManager |
| POST | `/consumables/{id}/restock` | Record a restock delivery | StoreManager |
| POST | `/collection-drops` | Create a licensed collection drop | StoreManager |
| GET | `/collection-drops/{id}` | Get a collection drop | Customer, WorkshopAssociate, StoreManager |
| GET | `/collection-drops/{id}/workshops` | List workshop sessions claiming units of this drop | WorkshopAssociate, StoreManager |
| POST | `/customers` | Register a customer | Customer |
| GET | `/customers/{id}` | Get a customer | Customer, StoreManager |
| GET | `/customers/{id}/workshops` | List a customer's workshop sessions | Customer, StoreManager |
| GET | `/customers/{id}/animals` | List a customer's stuffed animals | Customer, StoreManager |
| GET | `/customers/{id}/registries` | List a customer's registries | Customer, StoreManager |
| GET | `/customers/{id}/parties` | List a customer's party reservations | Customer, StoreManager |
| GET | `/customers/{id}/build-ship-orders` | List a customer's build-and-ship orders | Customer, StoreManager |
| POST | `/workshops` | Start a walk-in workshop session | WorkshopAssociate |
| GET | `/workshops/{id}` | Get a workshop session | Customer, WorkshopAssociate, StoreManager |
| POST | `/workshops/{id}/advance-step` | Advance the session one station step | WorkshopAssociate |
| POST | `/workshops/{id}/abandon` | Abandon a non-terminal session | WorkshopAssociate |
| POST | `/workshops/{id}/payment` | Pay for a dressed session | Customer |
| GET | `/animals/{id}` | Get a stuffed animal | Customer, WorkshopAssociate, StoreManager |
| GET | `/animals/{id}/workshops` | List workshop sessions whose minted animal this is | Customer, WorkshopAssociate, StoreManager |
| GET | `/workshops/{id}/animals` | List stuffed animals minted by this session | Customer, WorkshopAssociate, StoreManager |
| GET | `/workshops/{id}/party-guests` | List party guests whose session this is | Customer, PartyHost, StoreManager |
| GET | `/workshops/{id}/build-ship-orders` | List build-and-ship orders assembled by this session | WorkshopAssociate, StoreManager |
| POST | `/animals/{id}/birth-certificate` | Personalize the birth certificate | Customer |
| POST | `/animals/{id}/report-lost` | Report a completed animal lost | Customer |
| POST | `/animals/{id}/mark-recovered` | Mark a lost animal recovered | Customer |
| POST | `/animals/{id}/mark-found-cancel` | Cancel a lost report, returning the animal to completed | Customer |
| POST | `/parties` | Quote and create a party reservation | Customer |
| GET | `/parties/{id}` | Get a party reservation | Customer, PartyHost, StoreManager |
| POST | `/parties/{id}/pay-deposit` | Pay the deposit; books the appointment block and reserves a host | Customer |
| POST | `/parties/{id}/pay-balance` | Pay the remaining balance after finalize | Customer |
| POST | `/parties/{id}/finalize` | Finalize a confirmed party and compute the final amount due | StoreManager |
| POST | `/parties/{id}/cancel` | Cancel a party and compute the deposit refund | Customer |
| POST | `/parties/{id}/reschedule` | Move the party to a new start time (OCC-guarded) | Customer |
| GET | `/parties/{id}/guests` | List guests of a party | Customer, PartyHost, StoreManager |
| GET | `/parties/{id}/workshops` | List workshop sessions created for this party's guests | Customer, PartyHost, StoreManager |
| GET | `/parties/{id}/appointment-blocks` | List appointment blocks held by this party | Customer, PartyHost, StoreManager |
| POST | `/party-guests` | Add a guest to a reservation | Customer |
| GET | `/party-guests/{id}` | Get a party guest | Customer, PartyHost, StoreManager |
| POST | `/party-guests/{id}/confirm` | Confirm an invited guest | Customer |
| POST | `/party-guests/{id}/cancel` | Cancel a guest while the reservation is pre-confirmed | Customer |
| POST | `/build-ship-orders` | Place an online build-and-ship order | Customer |
| GET | `/build-ship-orders/{id}` | Get a build-and-ship order | Customer, WorkshopAssociate, StoreManager |
| GET | `/build-ship-orders/{id}/workshops` | List workshop sessions assembling this order | WorkshopAssociate, StoreManager |
| POST | `/build-ship-orders/{id}/start-assembly` | Begin store assembly; creates the linked workshop session | WorkshopAssociate |
| POST | `/build-ship-orders/{id}/handoff` | Hand a ready-for-pickup order to the carrier | WorkshopAssociate |
| POST | `/build-ship-orders/{id}/cancel` | Cancel a placed or in-assembly order | Customer |
| POST | `/gift-cards` | Issue a gift card | StoreManager |
| GET | `/gift-cards/{id}` | Get a gift card | Customer, StoreManager |
| POST | `/gift-cards/{id}/disable` | Disable a gift card | StoreManager |
| POST | `/registries` | Create a stuffed-animal registry | Customer |
| GET | `/registries/{id}` | Get a registry | Customer, StoreManager |
| POST | `/registries/{id}/link-animal` | Link a completed animal owned by the registry owner | Customer |
| POST | `/registries/{id}/link-gift-card` | Link a gift card to this registry | Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_OUTSIDE_TIME_WINDOW` | 409 |
| `ERR_DROP_LIMIT_REACHED` | 409 |
| `ERR_STATION_AT_CAPACITY` | 409 |
| `ERR_HOST_UNAVAILABLE` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_GIFT_CARD_INSUFFICIENT` | 409 |
| `ERR_GIFT_CARD_NOT_LINKED` | 409 |
| `ERR_REFERENTIAL_INTEGRITY` | 409 |
| `ERR_PARTY_GUEST_LIMIT` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 409 |
