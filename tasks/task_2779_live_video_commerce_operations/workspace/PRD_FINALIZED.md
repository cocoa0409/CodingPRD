# Live Video Commerce Operations API — Product Requirements Document

## 1. Introduction

Retail live shopping has collapsed three previously separate businesses — broadcast production, merchandising, and e-commerce checkout — into a single hour of airtime. A show goes to air across several simulcast destinations at once; a merchandiser opens a flash offer whose allotment is finite; a few thousand viewers add lines to persistent carts that hold real units out of a real fulfilment centre; a moderator screens chat and feeds questions to the host; and a compliance officer must be able to prove afterwards that every on-air claim was substantiated and every paid-endorsement disclosure was spoken. Today those five workstreams run on five disconnected tools, and the reconciliation between them is a spreadsheet exercise performed the morning after. The consequence is familiar: oversold flash offers, hosts who make claims nobody signed off, carts abandoned with inventory still locked behind them, and margin numbers that change every time somebody recalculates them.

This document specifies the API for a single system of record covering the whole live-commerce operation: show calendar planning with host booking and turnaround protection, product lineup composition with unit-cost snapshots, technical production across simulcast platforms with latency and drift management, real-time inventory and pricing synchronisation through time-boxed flash offers with hard quantity allotments, an interactive layer covering chat moderation, polls and viewer-question routing, in-stream checkout with cart persistence and abandonment recovery, disclosure and claim-accuracy controls, replay merchandising with time-stamped product links and post-show conversion attribution, and performance analytics by show, host and product with margin analysis.

Two design commitments run through everything that follows. The first is **immediate consistency**: every cascade, counter and derived field is reconciled inside the request that caused it — there is no background job, no eventual settlement, and no window in which the offer ledger and the inventory ledger disagree. The second is **auditable arithmetic**: every monetary and scoring formula in this specification pins its evaluation order and its rounding points, because a margin figure that depends on the order of summation is not an auditable figure. Implementations are expected to reproduce the stated order exactly, not merely to land on a plausible number.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to every endpoint must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is acting in. If either header is absent, or if `X-User-Role` is not one of the seven role names declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are well formed but the named role is not among the roles authorised for the endpoint being called (see the endpoint table in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The seven roles are `ShowProducer`, `MerchandisingManager`, `ComplianceOfficer`, `Moderator`, `Host`, `Viewer`, and `PlatformAdmin`.

- A `ShowProducer` owns show calendar planning and technical production: it creates shows and simulcast destinations, books hosts, registers disclosure obligations, and drives the show through readiness, air and end-of-broadcast. It cannot substantiate product claims, cannot certify hosts, and cannot sign a show off.
- A `MerchandisingManager` owns the product catalogue, physical inventory, the lineup, flash-offer pricing, replay merchandising, and order capture. It cannot move a show through its lifecycle and cannot substantiate the claims of the products it prices.
- A `ComplianceOfficer` is the independent control function: it substantiates product claims, certifies hosts for paid-endorsement disclosure, and signs the show off after air.
- A `Moderator` screens live chat and viewer questions and routes approved questions to the on-air host. It cannot submit an interaction, cannot answer a question, and cannot touch commerce state.
- A `Host` is on-air talent: it confirms its own bookings, acknowledges disclosure scripts, opens and closes polls, and answers or defers routed questions.
- A `Viewer` is the shopper: it keeps a persistent cart, buys inside the stream, chats, asks questions, and votes in polls.
- A `PlatformAdmin` is operations engineering: it registers viewers and hosts, drives the logical clock that every temporal rule reads, and holds unrestricted read access. It has no commerce, lifecycle or compliance write authority beyond viewer and host registration and the clock.

Two of the seven roles are **entity-backed**, meaning `X-User-ID` is not merely a label but a foreign key into persisted data.

When `X-User-Role` is `Host`, `X-User-ID` is the `id` of the acting `Host` row; ownership checks on any resource that references a `Host` compare the resource's host foreign-key field to `X-User-ID`. Concretely: confirming or cancelling a booking requires `X-User-ID` to equal that booking's `host_id`; acknowledging a disclosure requires `X-User-ID` to equal the `host_id` of the `HostBooking` named by the record's `host_booking_id`; closing a poll requires `X-User-ID` to equal that interaction's `host_id`; and answering or deferring a routed question requires `X-User-ID` to equal the `host_id` of the show's `PRIMARY` booking whose status is `CONFIRMED`. Any mismatch is `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

When `X-User-Role` is `Viewer`, `X-User-ID` is the `id` of the acting `Viewer` row; every cart, cart-line, order and interaction write compares the target row's `viewer_id` to `X-User-ID`, and a mismatch is likewise `ERR_NOT_RESOURCE_OWNER`. A viewer's own identity is also the *source* of ownership on creation: the `viewer_id` of a new cart and the `viewer_id` of a new chat or question are taken from `X-User-ID` and never from the request body, even if the body supplies one.

The remaining five roles — `ShowProducer`, `MerchandisingManager`, `ComplianceOfficer`, `Moderator`, and `PlatformAdmin` — carry **opaque** identity: `X-User-ID` is an operator identifier not tied to any persisted entity, and the server never compares it to an entity's `id`. The server does, however, record it where a rule later needs it: `Show.created_by_user_id` records the producer who created the show, `Product.substantiated_by_user_id` records the compliance officer who substantiated a claim, and `Show.compliance_signoff_by_user_id` records the officer who signed the show off. The segregation-of-duties rule in §2.12 compares two of those recorded opaque identifiers against each other, which is the one place an opaque identifier participates in an authorisation decision.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to `10`, may not be lower than `1`, and may not exceed `100`. `offset` defaults to `0` and may not be negative. A `limit` or `offset` outside those bounds is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a list endpoint explicitly documents another ordering, results are returned sorted by `created_at` ascending — oldest row first. Ordering is applied before the window, so `offset` and `limit` slice a stable sequence.

List responses populate four pagination fields inside `meta`: `limit` and `offset` echo the effective values used for the query, `total_count` is the number of rows matching the filters before the window is applied, and `has_more` is true when rows remain beyond the returned window. Single-resource reads and write responses carry `meta` without those four fields.

### 2.4. Resource Identity, Timestamps and Versioning

Every resource in this system — `Host`, `Product`, `Viewer`, `Show`, `StreamChannel`, `HostBooking`, `LineupSlot`, `FlashOffer`, `DisclosureRecord`, `Cart`, `CartItem`, `Order`, and `Interaction` — carries the same four common properties, and all thirteen carry all four.

- `id` is a server-minted UUID. It is generated by the server, never accepted from a client, and carries no type prefix or other decoration — it is the bare UUID string.
- `created_at` is the ISO 8601 UTC instant the row was created, rendered with exactly three fractional-second digits and a trailing `Z`.
- `updated_at` is the ISO 8601 UTC instant of the most recent mutation, in the same format. At creation it equals `created_at`.
- `version` is an integer that starts at `1` when the row is created and increments by exactly `1` on every mutation of that row, including mutations the row suffers as a side effect of an operation performed on a different resource.

The `version` counter is not decorative: it is the substrate of the concurrency control described in §2.8, and cascades increment it. When a single request advances a resource through two transitions — as the deferral loop in §3.8 does — `version` advances twice in that one request. Whenever `version` increments, `updated_at` is refreshed to the same logical instant.

### 2.5. The Logical Broadcast Clock

Nothing in this system reads the host machine's wall clock. Every rule that refers to "now" — certification expiry, the go-live window, flash-offer windows, mute lapses, cart-recovery deadlines, replay decay — reads a **logical clock** maintained by the server. That clock starts at exactly `2026-08-01T00:00:00Z`, and until an administrator moves it, every temporal comparison in the system is evaluated against that instant.

A `PlatformAdmin` moves the clock by supplying a `current_utc` instant; the response reports the new `current_utc` alongside `previous_utc`, the instant the clock held before the call. Moving the clock mutates no entity and fires no lazy transition: it does not expire an offer, does not lapse a mute, and does not settle a cart. Time-dependent consequences are evaluated when the affected operation is next attempted, which is why an over-deadline recovery attempt is refused at attempt time rather than pre-emptively cancelled.

Every timestamp supplied in a request body must be an ISO 8601 UTC value — either second precision with a trailing `Z`, or the three-fractional-digit form. Anything else is `ERR_INVALID_REQUEST`.

### 2.6. Flat Topology, Path Resolution and Reverse Lookups

The thirteen resources form a **flat** topology: no resource is nested inside another's URL. A cart line is addressed directly, not through its cart; a stream channel is addressed directly, not through its show. Relationships are expressed as foreign keys stored on the child row, and every reverse lookup is therefore a filtered flat collection rather than a nested path.

Path identifiers are resolved strictly left to right, and the first identifier that does not resolve determines the response. The path identifiers this API uses are `host_id`, `product_id`, `viewer_id`, `show_id`, `channel_id`, `booking_id`, `slot_id`, `offer_id`, `record_id`, `cart_id`, `item_id`, `order_id`, and `interaction_id`. Each maps to its own not-found code — `ERR_HOST_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_VIEWER_NOT_FOUND`, `ERR_SHOW_NOT_FOUND`, `ERR_STREAM_CHANNEL_NOT_FOUND`, `ERR_HOST_BOOKING_NOT_FOUND`, `ERR_LINEUP_SLOT_NOT_FOUND`, `ERR_FLASH_OFFER_NOT_FOUND`, `ERR_DISCLOSURE_RECORD_NOT_FOUND`, `ERR_CART_NOT_FOUND`, `ERR_CART_ITEM_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, and `ERR_INTERACTION_NOT_FOUND` — each returned with HTTP 404. Foreign keys supplied in a request body resolve to the same code family: an unknown `show_id`, `host_id`, `product_id`, `lineup_slot_id`, `flash_offer_id`, `host_booking_id` or `viewer_id` in a body yields that entity's not-found error.

The reverse-lookup collections accept the following filters, all optional and all combinable, and all narrowing by exact match: simulcast destinations by `show_id` and `status`; host bookings by `show_id`, `host_id` and `status`; lineup slots by `show_id` and `product_id`; flash offers by `lineup_slot_id`, `superseded_by_offer_id` and `status`; disclosure records by `show_id`, `host_booking_id` and `status`; carts by `show_id`, `viewer_id` and `status`; cart lines by `cart_id`, `flash_offer_id`, `lineup_slot_id` and `state`; orders by `cart_id`, `show_id`, `viewer_id` and `payment_state`; and interactions by `show_id`, `viewer_id`, `host_id`, `kind` and `state`. Each of these collections also accepts `limit` and `offset` as described in §2.3.

### 2.7. Order of Rejection: The Validation Ladder

A single malformed or ill-timed request frequently violates several rules at once. The response is not ambiguous: checks are evaluated in a **fixed priority order**, and the first check that fails decides the response entirely. A request that violates both the request-shape rule and the offer-allotment rule returns the request-shape error, because request shape is evaluated first. The ladder, from first evaluated to last, is:

1. **Header presence and role validity** — `ERR_UNAUTHENTICATED`.
2. **Role authorisation for the endpoint** — `ERR_ROLE_NOT_PERMITTED`.
3. **Resource ownership for entity-backed roles** — `ERR_NOT_RESOURCE_OWNER`. This applies to adding a cart line, abandoning a cart, recovering a cart, checking out a cart, cancelling an order, confirming a booking, cancelling a booking, acknowledging a disclosure record, and a host action on an interaction — nine operations in all.
4. **Path identifier existence**, left to right — the 404 family above.
5. **Body foreign-key existence** — the same 404 family. This applies to creating a host booking, a lineup slot, a flash offer, a stream channel, a disclosure record, a cart, a cart line, an interaction, and a replay conversion.
6. **Request shape** — required fields present, enum values inside their declared sets, numbers inside their declared ranges, timestamps well formed, and every declared ordering constraint satisfied (`scheduled_end_at` strictly after `scheduled_start_at`; `release_time_at` strictly after `call_time_at`; `window_end_at` strictly after `window_start_at`; `planned_end_at` strictly after `planned_start_at`; `offer_price_cents` no greater than the slot product's `base_price_cents`; `qty` at least 1 and at most 20; a poll's `options` array holding between two and four labels; `script_code_spoken` equal to the record's `required_script_code`; and a replay conversion's `occurred_at` at or after the show's `ended_at`). All of these are `ERR_INVALID_REQUEST` (HTTP 400).
7. **Stale-version rejection** — the optimistic-concurrency check of §2.8, yielding `ERR_STALE_LINEUP_SLOT_VERSION` or `ERR_STALE_CART_VERSION` (HTTP 412).
8. **Own-state legality** — the target resource must currently be in a state from which the requested transition is declared. The relevant field depends on the resource: `Show.status`, `HostBooking.status`, `StreamChannel.status`, `FlashOffer.status`, `Cart.status`, `Order.payment_state`, `Interaction.state`, or `DisclosureRecord.status`. The corresponding rejections are `ERR_INVALID_SHOW_STATE`, `ERR_INVALID_BOOKING_STATE`, `ERR_INVALID_CHANNEL_STATE`, `ERR_INVALID_OFFER_STATE`, `ERR_INVALID_CART_STATE`, `ERR_INVALID_ORDER_STATE`, `ERR_INVALID_INTERACTION_STATE`, and `ERR_INVALID_DISCLOSURE_STATE`, all HTTP 409.
9. **Related-entity state gating** — the *other* entity whose state licenses the operation. The show must be `LIVE` for offer activation, cart-line addition, checkout, interaction submission, moderation, routing, host action, poll voting and order capture; the booking's show must be `DRAFT` or `READY` for booking confirmation, booking cancellation and channel provisioning; the show must be `DRAFT`, `READY` or `LIVE` for disclosure-record creation and acknowledgement; and the show must be `ENDED` or `SETTLED` for replay-marker setting, replay-marker publication and replay-conversion recording, because the replay does not exist until the broadcast is off air. Additionally, the flash offer backing a line being added must be `ACTIVE`. These rejections are `ERR_INVALID_SHOW_STATE`, `ERR_OFFER_NOT_ACTIVE` and `ERR_SHOW_NOT_ENDED`, all HTTP 409.
10. **Claim substantiation** — `ERR_CLAIM_NOT_SUBSTANTIATED` (HTTP 422), guarding the readiness gate, offer activation and cart-line addition.
11. **Outstanding disclosures** — `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` (HTTP 422), guarding the readiness gate.
12. **Host certification** — `ERR_HOST_CERTIFICATION_EXPIRED` (HTTP 422), guarding booking confirmation and the readiness gate.
13. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), guarding compliance sign-off.
14. **Host booking overlap** — `ERR_HOST_BOOKING_OVERLAP` (HTTP 409), guarding booking creation.
15. **Offer window overlap** — `ERR_OFFER_WINDOW_OVERLAP` (HTTP 409), guarding offer creation.
16. **Offer window currency** — `ERR_OFFER_WINDOW_CLOSED` (HTTP 409), guarding offer activation and cart-line addition.
17. **Go-live window** — `ERR_GO_LIVE_WINDOW_CLOSED` (HTTP 409), guarding the go-live transition.
18. **Recovery window** — `ERR_RECOVERY_WINDOW_CLOSED` (HTTP 409), guarding cart recovery.
19. **Offer/cart show agreement** — `ERR_OFFER_SHOW_MISMATCH` (HTTP 422), guarding cart-line addition.
20. **Primary-host uniqueness** — `ERR_PRIMARY_HOST_CONFLICT` (HTTP 409), guarding booking creation.
21. **Primary-host presence** — `ERR_PRIMARY_HOST_MISSING` (HTTP 422), guarding the readiness gate and go-live.
22. **Non-empty lineup** — `ERR_LINEUP_EMPTY` (HTTP 422), guarding the readiness gate.
23. **Simulcast readiness** — `ERR_SIMULCAST_NOT_READY` (HTTP 422), guarding the readiness gate and go-live.
24. **Viewer mute** — `ERR_VIEWER_MUTED` (HTTP 403), guarding interaction submission and poll voting.
25. **Poll eligibility** — `ERR_POLL_NOT_OPEN` or `ERR_DUPLICATE_VOTE` (HTTP 409), guarding poll voting.
26. **Deferral ceiling** — `ERR_DEFERRAL_LIMIT_REACHED` (HTTP 409), guarding host actions.
27. **Replay marker readiness** — `ERR_REPLAY_MARKER_NOT_PUBLISHED` (HTTP 409) and `ERR_MARKER_OFFSET_OUT_OF_RANGE` (HTTP 422), guarding replay-marker setting and replay-conversion recording.
28. **Basket non-emptiness** — `ERR_EMPTY_CART` (HTTP 422) at checkout and `ERR_NO_RECOVERABLE_ITEMS` (HTTP 409) at recovery.
29. **Distinct-line ceiling** — `ERR_CART_ITEM_LIMIT` (HTTP 422), guarding cart-line addition.
30. **Offer allotment** — `ERR_OFFER_QTY_EXCEEDED` (HTTP 422), guarding cart-line addition and cart recovery.
31. **Physical inventory** — `ERR_INSUFFICIENT_INVENTORY` (HTTP 422), guarding cart-line addition, cart recovery and inventory adjustment.

The last two rungs deserve emphasis because they are frequently conflated. Allotment and physical stock are separate ledgers with separate ceilings (§2.10), the allotment ceiling is checked first, and an add that would clear the offer's allotment but exceed the product's free units is rejected with `ERR_INSUFFICIENT_INVENTORY`, not with `ERR_OFFER_QTY_EXCEEDED`.

### 2.8. Optimistic Concurrency on Slot Pricing and Basket Checkout

Exactly two write operations in this API require the client to prove it is working from a current view of a parent resource, and both use the same mechanism: a non-optional integer field in the request body carrying the client's last observed `version` of that parent.

Creating a flash offer — `POST /flash-offers` — requires `expected_lineup_slot_version` to equal the current `version` of the `LineupSlot` named by `lineup_slot_id`. If they differ, the create is rejected with `ERR_STALE_LINEUP_SLOT_VERSION` (HTTP 412) and nothing is written. The reason is that a newly created offer legitimately retires any `SCHEDULED` offer already standing on the same slot, so a create issued from a stale view of the slot would silently supersede pricing the client never saw. The stale-version check converts that silent overwrite into a deterministic rejection.

Checking out a cart — `POST /carts/{cart_id}/checkout` — requires `expected_cart_version` to equal the target cart's current `version`. If they differ, the checkout is rejected with `ERR_STALE_CART_VERSION` (HTTP 412) and no order is created. Adding a line, abandoning and recovering all advance `Cart.version` and re-lock line pricing, so a checkout carrying an older version would convert a basket whose totals the client never observed.

No other endpoint accepts a version field. Requests to any other endpoint must not be expected to supply one, and supplying one has no effect.

### 2.9. Money, Units, Fractions and Rounding

All monetary amounts in this API are **integer counts of cents**. There are no decimal currency fields, and no monetary value is ever transported as a float or a string. Where this document expresses a monetary threshold in dollars, the stored and compared value is the cent equivalent — a threshold of 75 dollars is a comparison against 7,500 cents.

Wherever a monetary computation produces a fractional cent, it is rounded **half up** to a whole cent: a value ending in exactly one half cent rounds away from zero. Rounding never happens at an arbitrary point; every formula in §3 names its rounding points, and those points are part of the contract. In particular, line tax is rounded per line and the rounded line taxes are then summed — summing the untaxed line totals first and rounding a single tax figure at the end is explicitly *not* the rule and yields a different cent total for the same basket.

Two non-monetary fields are fractions rather than integers. `Host.commission_pct` is a fraction between `0.0` and `0.30` inclusive. `Cart.bundle_discount_pct` is an exact two-decimal fraction drawn from the tier table in §3.6, and `StreamChannel.dropped_frame_pct` is a fraction between `0.0` and `1.0` inclusive. Scoring outputs — the readiness index, the host effectiveness score, and the abandonment rate in basis points — are integers, each with its own single rounding point stated where the formula is given.

Every threshold comparison in this specification is stated with its boundary inclusivity spelled out, and boundaries are load-bearing. A subtotal landing exactly on a discount floor takes that tier. A merchandise total landing exactly on the free-shipping threshold ships free. A readiness index landing exactly on the go-live floor passes the gate. A gap landing exactly on the host turnaround buffer is accepted.

### 2.10. Two Ledgers: Physical Inventory and Offer Allotment

Selling inside a live stream means two independent scarcities are in play at once, and this system tracks both explicitly rather than collapsing them.

The **physical ledger** lives on `Product`. `on_hand_qty` is the count of units sitting in the fulfilment centre and is mutated only by an inventory adjustment. `reserved_qty` is the total `qty` across all cart lines currently in state `HELD` that point (through their lineup slot) at this product. `committed_qty` is the same total across lines in state `COMMITTED`. `available_qty` is `on_hand_qty` less `reserved_qty` less `committed_qty`. Cart lines in state `RELEASED` contribute to none of these totals.

The **allotment ledger** lives on `FlashOffer`. `max_qty` is the hard allotment the merchandiser opened. `held_qty` is the total `qty` across this offer's cart lines in state `HELD`; `sold_qty` is the same total across lines in state `COMMITTED`; and `remaining_qty` is `max_qty` less `held_qty` less `sold_qty`.

Both ledgers are reconciled inside every request that could move a line between states — every hold, every commit at checkout, every release from offer expiry, offer cancellation, cart abandonment or order cancellation, every re-hold during cart recovery, and every inventory adjustment. Two conservation invariants must hold after every single request, without exception. First, a product's `on_hand_qty` always equals `available_qty` plus `reserved_qty` plus `committed_qty`. Second, an offer's `max_qty` always equals `remaining_qty` plus `held_qty` plus `sold_qty`. Both ledgers are integer-valued and no rounding is involved. A hold followed by its release must return `available_qty` to its exact pre-hold value; a checkout followed by an order cancellation must return `remaining_qty` to its exact pre-checkout value.

An inventory adjustment is the one operation that changes `on_hand_qty` directly. It moves `available_qty` with it and never touches `reserved_qty` or `committed_qty`, and an adjustment that would drive `available_qty` below zero is refused with `ERR_INSUFFICIENT_INVENTORY`.

### 2.11. Cascade Discipline and Compound Readiness

Several operations in this system reach far beyond the resource they name. Ending a broadcast expires offers, which releases cart lines, which abandons carts, which moves show-level counters — four links deep, all inside the one request. Blocking a chat message adds a strike, which can mute a viewer, which withdraws that viewer's other pending interactions, which moves the show's pending-question counter — five links deep. Cancelling a confirmed primary booking can revert the show, which cancels its scheduled offers, which releases their held lines, which decrements both ledgers.

Three rules govern all such cascades uniformly. Every entity a cascade touches has its `version` incremented and its `updated_at` refreshed, exactly as if it had been written directly. Every derived counter downstream of a cascade is recomputed inside the same request, so a read issued immediately after sees fully reconciled values. And a cascade never partially applies: if the triggering operation succeeds, every link fires.

`Show.status` is **compound**, not merely sequential: `READY` is a derived assertion about the show's booking, disclosure, claim, channel and lineup state, and it can be *lost*. When the confirmed primary booking is cancelled, or when a health report leaves the show with no channel in `PROVISIONED` or `LIVE`, a `READY` show falls back to `DRAFT` and the producer must re-run the readiness gate. A `LIVE` show is never reverted by a channel failure — only `READY` shows revert.

`Order` state is likewise not a single chain but two **independent dimensions**: `payment_state` and `fulfillment_state` are stored separately and move separately. Capture advances both; cancellation moves fulfilment to `CANCELLED` while the payment dimension takes whichever terminal value matches what has already been collected.

### 2.12. Segregation of Duties Across the Compliance Chain

The compliance controls in this system are worthless if one person can operate both ends of them, so three separations are enforced structurally rather than by policy. Producers cannot certify hosts for paid-endorsement disclosure and cannot substantiate product claims — both are `ComplianceOfficer` operations. Hosts acknowledge only their own disclosure obligations, never another host's. And the officer who signs a show off must not be the officer who substantiated the claim of any product that show merchandised.

That last separation is checked at sign-off time by comparing the signing officer's `X-User-ID` against `Product.substantiated_by_user_id` on every product reachable through the show's lineup slots. If the signing officer's identifier equals any of them, sign-off is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) and the show remains `ENDED`. The practical consequence is that a live-commerce operation needs at least two compliance officers on any show whose products carry claims.

## 3. Business Logic & Workflows

### 3.1. Show Calendar Planning, Host Booking and Disclosure Obligations

Planning a broadcast begins with a `ShowProducer` placing a show on the calendar. The producer supplies a `title` and the planned airtime as `scheduled_start_at` and `scheduled_end_at`, the latter strictly after the former. The new show enters `DRAFT` — the status in which its lineup, bookings and simulcast destinations are assembled, and lineup slots and bookings may still be added while the show sits in `READY`, whereas simulcast destinations may be attached in `DRAFT` alone — and the server stamps `created_by_user_id` with the producer's `X-User-ID` and initialises every derived counter on the show to zero. Attempting to mutate a show's lineup or bookings once it has left `DRAFT` and `READY` behind is refused with `ERR_INVALID_SHOW_STATE`.

On-air talent is registered separately, by a `ShowProducer` or a `PlatformAdmin`, with a `full_name`, a `handle`, and a `commission_pct`. The `handle` is the social identity the host uses on every simulcast platform and must be unique across all hosts and between three and thirty characters long; a duplicate or out-of-range handle is `ERR_INVALID_REQUEST`. `commission_pct` is the fraction of merchandise revenue the host accrues and must lie between `0.0` and `0.30` inclusive. A freshly registered host is not yet allowed to work a paid-endorsement show: `certification_status` initialises to `UNCERTIFIED` and `disclosure_certification_expires_at` is null.

Certification is a `ComplianceOfficer` duty. The officer records or renews a host's paid-endorsement disclosure certification by supplying `certified_until`, which the server writes to `disclosure_certification_expires_at`. `certification_status` is never stored independently of that instant — it is derived on every read: `UNCERTIFIED` when `disclosure_certification_expires_at` is null, `EXPIRED` when `disclosure_certification_expires_at` is strictly earlier than the logical clock's current instant, and `CERTIFIED` otherwise. A certification whose expiry lands exactly on the current instant is therefore still `CERTIFIED`. Recording a certification bumps the host's `version`.

Booking a host onto a show is again the producer's act, and the payload names the `show_id` and the `host_id` alongside a `role` of either `PRIMARY` or `GUEST`, the occupied interval as `call_time_at` and `release_time_at`, and a flat appearance `fee_cents` of zero or more. The interval is **half-open**: `call_time_at` is inclusive and `release_time_at` is exclusive, and `release_time_at` must be strictly after `call_time_at`. `fee_cents` is informational — commission is computed separately from merchandise revenue and never from the appearance fee. A new booking enters `PENDING`.

Two constraints bite at booking creation. The first protects the host physically. Hosts need time to travel between sets and change wardrobe, so each booked interval is expanded by a **turnaround buffer of three quarters of an hour** on both sides before it is compared against the host's other bookings. Concretely, over the existing bookings of the same `host_id` whose status is `PENDING` or `CONFIRMED`, the new booking is rejected when the new `call_time_at` is earlier than the existing `release_time_at` advanced by 45 minutes *and* the existing `call_time_at` is earlier than the new `release_time_at` advanced by 45 minutes. Both conditions must hold for a collision. A gap of exactly 45 minutes between one booking's release and the next booking's call time is accepted; a gap of 44 minutes is rejected with `ERR_HOST_BOOKING_OVERLAP`. Cancelled and completed bookings are invisible to this check.

The second constraint protects the broadcast. A show has at most one lead presenter: if the show already carries a booking with `role` equal to `PRIMARY` whose status is `PENDING` or `CONFIRMED`, a second `PRIMARY` booking is refused with `ERR_PRIMARY_HOST_CONFLICT`. Any number of `GUEST` bookings is permitted. A previously cancelled `PRIMARY` booking does not block a replacement.

A booking is not real until the talent accepts it. Only the booked host may accept — `X-User-ID` must equal the booking's `host_id`, or the request is `ERR_NOT_RESOURCE_OWNER` — and acceptance moves the booking `PENDING → CONFIRMED`, stamping `confirmed_at` with the logical instant and incrementing `version`. Acceptance is refused unless the booking is still `PENDING` (`ERR_INVALID_BOOKING_STATE`), unless the show is in `DRAFT` or `READY` (`ERR_INVALID_SHOW_STATE`), and unless the host's `certification_status` is `CERTIFIED` at that moment (`ERR_HOST_CERTIFICATION_EXPIRED`).

Cancellation is available to the booking's own host and to a `ShowProducer`, requires a `cancel_reason`, and works from either `PENDING` or `CONFIRMED`, in both cases while the show is still in `DRAFT` or `READY`. Both branches record `cancel_reason`, increment the booking's `version`, and void the paperwork: every disclosure record naming this booking through `host_booking_id` whose status is still `PENDING` moves `PENDING → VOIDED`, with its own `version` incremented. Cancelling a `CONFIRMED` booking whose `role` is `PRIMARY` while the show sits in `READY` triggers a deeper chain, described in §3.4.

Disclosure obligations are registered by the producer against a specific booking. The payload carries the `show_id`, the `host_booking_id`, a `disclosure_type` of `PAID_ENDORSEMENT`, `MATERIAL_CONNECTION` or `FREE_PRODUCT`, and the `required_script_code` naming the approved on-air wording. A record whose `host_booking_id` belongs to a different show than the body's `show_id` is internally inconsistent and rejected with `ERR_INVALID_REQUEST`. Registration is legal while the show is in `DRAFT`, `READY` or `LIVE` — an unplanned paid mention can be papered mid-broadcast — and the new record enters `PENDING`. Attempting registration on an `ENDED` or `SETTLED` show is `ERR_INVALID_SHOW_STATE`.

Only the booked host may acknowledge, and the acknowledgement must quote the script: the payload supplies `script_code_spoken`, which must equal the record's `required_script_code`, or the request is `ERR_INVALID_REQUEST`. `X-User-ID` must equal the `host_id` of the booking named by `host_booking_id` (`ERR_NOT_RESOURCE_OWNER`), the record must still be `PENDING` — a record already `ACKNOWLEDGED`, or one already `VOIDED` by a booking cancellation, is refused with `ERR_INVALID_DISCLOSURE_STATE`, the booking must be `PENDING` or `CONFIRMED` (`ERR_INVALID_BOOKING_STATE`), and the show must be in `DRAFT`, `READY` or `LIVE` (`ERR_INVALID_SHOW_STATE`). Acknowledgement moves the record `PENDING → ACKNOWLEDGED`, stamps `acknowledged_at` with the logical instant, increments `version`, and computes `acknowledged_late`: the flag is true when `acknowledged_at` is set, the show's `went_live_at` is set, and `acknowledged_at` is strictly later than `went_live_at` — that is, when the host spoke the disclosure only after the broadcast had already started. Otherwise the flag is false. Late acknowledgements are not blocked, but they cost the host points in the effectiveness score of §3.9.

### 3.2. The Product Catalogue, Claim Substantiation and Lineup Composition

The catalogue is a `MerchandisingManager` responsibility. Creating a product takes a `sku` unique across the catalogue, a merchandising `title` shown in-stream, a `base_price_cents` between 100 and 5,000,000 inclusive, a `unit_cost_cents` of at least zero and strictly less than `base_price_cents`, an `on_hand_qty` of at least zero, and optionally a `claim_text` — the specific claim the host is permitted to state on air. A duplicate `sku`, a cost that is not strictly below list price, or a price outside its range is `ERR_INVALID_REQUEST`. At creation, `reserved_qty` and `committed_qty` are zero, `available_qty` equals `on_hand_qty`, and `claim_substantiation_status` initialises to `UNSUBSTANTIATED` with `substantiated_by_user_id` and `substantiated_at` both null.

Inventory and cost are revisable, and both revisions travel on the same adjustment operation, which requires a free-text `reason` and accepts an optional `on_hand_delta` and an optional `unit_cost_cents`. The delta — which may be negative — is applied to `on_hand_qty`, `available_qty` is recomputed against the reservation and commitment totals, and the product's `version` is incremented. An adjustment that would push `available_qty` below zero is refused with `ERR_INSUFFICIENT_INVENTORY`; an adjustment never moves `reserved_qty` or `committed_qty`. Supplying `unit_cost_cents` replaces the product's current landed cost — this is the post-show cost revision that the final margin variant reads — and it deliberately does **not** touch the `unit_cost_snapshot_cents` already recorded on any lineup slot. The gap between those two numbers is exactly what distinguishes the provisional margin from the final one.

Claim accuracy is a `ComplianceOfficer` control, exercised through a substantiation decision carrying a `decision` of `UNSUBSTANTIATED`, `SUBSTANTIATED` or `REJECTED` and an optional `evidence_ref`. The decision is written straight to `claim_substantiation_status`. A `SUBSTANTIATED` decision additionally stamps `substantiated_by_user_id` with the officer's `X-User-ID` and `substantiated_at` with the logical instant — the two fields the segregation-of-duties check of §2.12 later reads. A `REJECTED` decision clears both back to null. Either way the product's `version` increments.

Composing a lineup is the merchandiser's act of deciding what is sold, in what order, and for how long. Each segment names the `show_id` and the `product_id`, a one-based `slot_sequence` giving on-air order, the segment's `planned_start_at` and `planned_end_at`, and a `planned_qty` of at least one unit the merchandiser intends to move. `slot_sequence` must be at least 1 and unique within the show; a duplicate sequence number on the same show is `ERR_INVALID_REQUEST`. `planned_end_at` must be strictly after `planned_start_at`, and both must fall inside the show's planned airtime — no earlier than `scheduled_start_at` and no later than `scheduled_end_at` — with a segment reaching outside that envelope rejected as `ERR_INVALID_REQUEST`.

Slot creation performs one quiet but consequential act: it copies the product's current `unit_cost_cents` into the slot's `unit_cost_snapshot_cents`. That frozen number is the cost basis the provisional margin uses forever after, no matter how the catalogue cost later moves. A newly created slot also initialises `replay_marker_status` to `NONE`, and — because the lineup is part of the show's readiness picture — the parent show's `version` is incremented.

### 3.3. Simulcast Production, Channel Health and the Readiness Index

A show does not go out on one pipe. The producer attaches a **simulcast destination** for each place the broadcast appears, naming the `show_id`, the `platform` — one of `FLAGSHIP_APP`, `SOCIAL_A`, `SOCIAL_B` or `PARTNER_APP` — and the contracted glass-to-glass `target_latency_ms` for that destination, which must be between 500 and 8,000 inclusive. The optional `is_primary` flag, false by default, marks the destination whose latency serves as the reference clock when the team discusses drift. A show may carry each `platform` at most once: a second destination on the same `platform` for the same `show_id` is `ERR_INVALID_REQUEST`. A new destination enters `DRAFT` with `readiness_index` at 0, `latency_ms` null, `dropped_frame_pct` at `0.0` and `health_report_count` at 0. Destinations may only be attached while the show is in `DRAFT`.

Provisioning takes the destination `DRAFT → PROVISIONED` and is permitted while the show is in `DRAFT` or `READY`; the same operation also serves as recovery, taking a destination `FAILED → PROVISIONED` and closing the `PROVISIONED → FAILED → PROVISIONED` cycle. The recovery branch additionally recomputes the show's `simulcast_readiness_index`, because bringing a destination back into service can lift the show out of an unbroadcastable state; the first-provisioning branch only increments the destination's `version`. Provisioning a destination that is already `PROVISIONED`, `LIVE` or `ENDED` is `ERR_INVALID_CHANNEL_STATE`, and provisioning against a show that has already gone `LIVE` or beyond is `ERR_INVALID_SHOW_STATE`.

Health is reported from the encoder, by a `ShowProducer` or a `PlatformAdmin`, and each report carries a measured `latency_ms` and a `dropped_frame_pct` fraction between `0.0` and `1.0` inclusive. The report is stored onto the destination as its latest `latency_ms` and `dropped_frame_pct`, `health_report_count` is incremented, and the destination's `version` is incremented. A health report against a destination still in `DRAFT`, or one already `ENDED`, is `ERR_INVALID_CHANNEL_STATE`.

The `readiness_index` is a 0-to-100 grade combining three penalties, and it is worth understanding why they interact. The first penalty is **absolute latency**, measured against a system-wide reference of one and a half seconds rather than against the destination's own contracted `target_latency_ms`: take the destination's reported `latency_ms`, subtract 1,500 milliseconds, divide by 50 milliseconds, and floor the result at zero — so every 50 milliseconds beyond a second and a half costs one point, and anything at or under the reference costs nothing. The second penalty is **frame loss**: the reported `dropped_frame_pct` multiplied by 400, so losing one percent of frames costs four points and losing a quarter of them costs a hundred. The third penalty is **simulcast drift**, and it is a property of the show rather than of the destination in isolation. Across the show's *reported* destinations — those whose status is `PROVISIONED` or `LIVE` and whose `latency_ms` is not null — take the largest reported `latency_ms` minus the smallest; that difference is the spread. Subtract a drift tolerance of 800 milliseconds from the spread, divide by 100 milliseconds, and floor at zero. Destinations on `PARTNER_APP` are exempt: their drift penalty is always zero, because the partner surface is not expected to stay in sync with the flagship. For every other `platform`, the drift penalty applies in full.

The three penalties are carried as exact decimal values, summed, and the **sum** is rounded half up exactly once. That single rounded figure is subtracted from 100, and the result is clamped into the range 0 to 100 — never below zero, never above one hundred. Rounding each penalty separately before summing is not the rule and will produce different indices.

One health report recomputes more than the reporting destination. Because the spread changes, the report recomputes `readiness_index` for **every** reported destination of the show, not just the one that filed the report, and only then recomputes the show-level figure. `Show.simulcast_readiness_index` is the *minimum* `readiness_index` across the show's destinations whose status is `PROVISIONED` or `LIVE`; when that set is empty the show-level figure is 0. A destination that has been provisioned but has never filed a report keeps `readiness_index` at 0 and is excluded from the spread calculation, but it is still a member of the `PROVISIONED` set — so a single silent destination floors the whole show's index at 0. The show-level figure is also recomputed on the readiness gate, on go-live, and on every destination status change.

A destination whose recomputed `readiness_index` falls **below 40** is unfit to carry the broadcast and transitions to `FAILED` — from `PROVISIONED` or from `LIVE` alike. Both failure branches recompute the show's `simulcast_readiness_index` over whatever destinations remain in `PROVISIONED` or `LIVE`, and both increment the destination's `version`. The branches differ in one respect: when the failure leaves a show sitting in `READY` with **zero** destinations remaining in `PROVISIONED` or `LIVE`, that show falls back `READY → DRAFT`. A show that is already `LIVE` is never reverted by a destination failure — the broadcast continues on whatever pipes survive, and the producer's remedy is to re-provision.

### 3.4. The Readiness Gate, Going Live, and Losing Readiness

Readiness is the moment a producer asserts that everything legally and technically required to air has been done. Running the gate moves the show `DRAFT → READY` and is refused unless the show is currently `DRAFT` (`ERR_INVALID_SHOW_STATE`). Six substantive conditions are then examined, and because a badly prepared show usually fails several at once, the order is fixed by the ladder in §2.7: claim substantiation is examined first, then outstanding disclosures, then host certification, then primary-host presence, then lineup emptiness, and finally simulcast readiness.

- **Claim substantiation.** Every product reachable through this show's lineup slots must carry `claim_substantiation_status` equal to `SUBSTANTIATED`. Any product still `UNSUBSTANTIATED` or `REJECTED` fails the gate with `ERR_CLAIM_NOT_SUBSTANTIATED`.
- **Outstanding disclosures.** No disclosure record belonging to this show may still be `PENDING`; a single unacknowledged obligation fails the gate with `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`. Records already `VOIDED` by a booking cancellation do not block readiness.
- **Host certification.** The confirmed primary host's `certification_status` must be `CERTIFIED` at gate time, evaluated against the logical clock. A lapsed certification fails with `ERR_HOST_CERTIFICATION_EXPIRED`, even though the same booking confirmed successfully at an earlier instant.
- **Primary-host presence.** Exactly one booking of this show must carry `role` equal to `PRIMARY` with status `CONFIRMED`; zero such bookings fails with `ERR_PRIMARY_HOST_MISSING`.
- **Non-empty lineup.** The show must have at least one lineup slot; a show with none fails with `ERR_LINEUP_EMPTY`.
- **Simulcast readiness.** At least one of the show's destinations must be `PROVISIONED`. If none is, the gate fails with `ERR_SIMULCAST_NOT_READY`. Note that at this stage the requirement is presence, not quality — the numeric index gate applies later.

A show that clears all six recomputes `simulcast_readiness_index` from the current destination health, stamps `readiness_checked_at` with the logical instant, and increments its `version`.

Going live moves the show `READY → LIVE`, and it is the single most temporally constrained operation in the system. Three conditions apply, resolved in ladder order — window first, then primary-host presence, then the numeric index gate. The **go-live window** opens half an hour before the planned start and closes at the planned end: the logical instant must be at or after `scheduled_start_at` minus 30 minutes, and strictly before `scheduled_end_at`. A producer trying to open the stream 31 minutes early, or one second after the planned end, is refused with `ERR_GO_LIVE_WINDOW_CLOSED`. The show's confirmed `PRIMARY` booking must still be `CONFIRMED` — a cancellation between readiness and airtime yields `ERR_PRIMARY_HOST_MISSING`. And the show's `simulcast_readiness_index`, recomputed immediately before the comparison, must be **at least 70**; an index of exactly 70 passes, an index of 69 is refused with `ERR_SIMULCAST_NOT_READY`. Going live from any status other than `READY` is `ERR_INVALID_SHOW_STATE`.

Upon a successful go-live the show stamps `went_live_at` with the logical instant, increments its `version`, and every destination of the show currently in `PROVISIONED` transitions `PROVISIONED → LIVE`, each with its own `version` incremented. Destinations still in `DRAFT` or `FAILED` are left where they are.

Readiness can be lost, and losing it is a cascade rather than a status change. A show falls `READY → DRAFT` in exactly two circumstances: when the `CONFIRMED` `PRIMARY` booking is cancelled, and when a health report leaves the show with no destination in `PROVISIONED` or `LIVE`. The reversion runs four links deep. First, the show's status returns to `DRAFT`, `readiness_checked_at` is refreshed to the logical instant, and `version` increments. Second, every flash offer still in `SCHEDULED` whose lineup slot belongs to this show transitions `SCHEDULED → CANCELLED`, each bumping its own `version` — pricing planned for a show that can no longer air is retired rather than left standing. Third, each cancelled offer releases every cart line of that offer still in state `HELD`, setting the line's `state` to `RELEASED`, its `released_reason` to `OFFER_CANCELLED` and its `released_at` to the logical instant. Fourth, each released line decrements the product's `reserved_qty` and the offer's `held_qty` by that line's `qty`, and both `available_qty` and `remaining_qty` are recomputed. Shoppers holding units against a reverted show therefore lose their holds, and the physical units return to `available_qty` immediately.

### 3.5. Flash Offers: Windows, Allotment and Supersession

A flash offer is the pricing instrument that makes live commerce urgent: a discounted per-unit price, valid only inside a stated window, capped at a stated number of units. A `MerchandisingManager` creates one against a lineup slot, naming the `lineup_slot_id`, the `offer_price_cents` charged per unit before any cart bundle discount, the `window_start_at` and `window_end_at` bounding validity, the `max_qty` allotment, and `expected_lineup_slot_version` as described in §2.8.

The numeric constraints are strict. `offer_price_cents` must be at least 1 and no greater than the `base_price_cents` of the slot's product — a flash offer may match list price but never exceed it. `max_qty` must be at least 1 and no more than 100,000. `window_end_at` must be strictly after `window_start_at`. Violations of any of these are `ERR_INVALID_REQUEST`. The window is a **closed** interval: both `window_start_at` and `window_end_at` are themselves inside validity.

Because a product cannot be simultaneously offered at two flash prices, offer windows are checked for collision **per product across every show**, not merely within one show or one slot. Over all existing offers whose status is `SCHEDULED`, `ACTIVE` or `EXHAUSTED` and whose lineup slot points at the same `product_id` as the new offer's slot, the create is rejected when the new `window_start_at` is at or before the existing `window_end_at` **and** the existing `window_start_at` is at or before the new `window_end_at`. Because the comparison is inclusive on both sides and no buffer is applied, **touching windows collide**: an offer starting at the exact instant an existing offer ends is rejected with `ERR_OFFER_WINDOW_OVERLAP`. Offers already `EXPIRED`, `CANCELLED` or `SUPERSEDED` are invisible to the check.

A successful create enters `SCHEDULED` with `held_qty` and `sold_qty` at zero and `remaining_qty` equal to `max_qty`, and `activated_at` null. Two further effects follow. Any offer already standing on the same lineup slot in status `SCHEDULED` transitions `SCHEDULED → SUPERSEDED`, has its `superseded_by_offer_id` set to the new offer's `id`, and has its own `version` incremented — this self-referential link is how the pricing history of a slot stays auditable, and it is the reason a stale-slot create is refused rather than tolerated. And the slot's own `version` is incremented, which means a client that creates two offers against the same slot must re-read the slot between them.

Activation is the moment the offer becomes purchasable, moving `SCHEDULED → ACTIVE`. Four conditions apply, resolved in ladder order: the offer must be `SCHEDULED` (an already-active, exhausted, expired, cancelled or superseded offer yields `ERR_INVALID_OFFER_STATE`); the show reached through the offer's lineup slot must be `LIVE` (`ERR_INVALID_SHOW_STATE`); the slot's product must carry `claim_substantiation_status` equal to `SUBSTANTIATED` (`ERR_CLAIM_NOT_SUBSTANTIATED`); and the logical instant must lie inside the closed window — at or after `window_start_at` and at or before `window_end_at` — with anything outside refused as `ERR_OFFER_WINDOW_CLOSED`. Activation stamps `activated_at` with the logical instant, recomputes `remaining_qty` as `max_qty` less `held_qty` less `sold_qty`, and increments the offer's `version`.

The allotment then governs the offer's own status without any operator involvement. Whenever a hold or a checkout commitment drives the recomputed `remaining_qty` to exactly 0, an `ACTIVE` offer transitions `ACTIVE → EXHAUSTED` in that same request, with `version` incremented. The reverse also happens: when a release cascade — an order cancellation, most commonly — returns allotment so that the recomputed `remaining_qty` is at least 1, an `EXHAUSTED` offer transitions `EXHAUSTED → ACTIVE`, provided the logical instant is still at or before `window_end_at` and the show is still `LIVE`. If the window has already closed, or the show is no longer `LIVE`, the offer stays `EXHAUSTED` even though allotment is available. This is the `ACTIVE → EXHAUSTED → ACTIVE` restock cycle, and it is bounded only by the window.

Two terminal fates arrive by cascade rather than by request. A show reverting out of `READY` cancels its `SCHEDULED` offers as described in §3.4. A show ending expires them: offers in `SCHEDULED`, `ACTIVE` or `EXHAUSTED` all move to `EXPIRED`, and the two branches that could still be holding units — the `ACTIVE` and `EXHAUSTED` branches — additionally release every cart line of that offer still in state `HELD`, setting `state` to `RELEASED` and `released_reason` to `OFFER_EXPIRED`, decrementing the product's `reserved_qty` and the offer's `held_qty` by each released `qty`, and recomputing `available_qty` and `remaining_qty`. The `SCHEDULED → EXPIRED` branch has no lines to release — a never-activated offer can never have been added to a cart — and so only increments `version`. All three branches increment the offer's `version`.

### 3.6. In-Stream Carts: Holds, Bundle Pricing and the Locked Line

A `Viewer` opens a cart against one show by supplying the `show_id`; the server sets `viewer_id` from `X-User-ID` — never from the body — and the cart enters `OPEN` with `recovered_count` at 0, `held_item_count` at 0, `pre_discount_subtotal_cents` at 0 and `bundle_discount_pct` at `0.0`. `abandoned_at`, `recovery_deadline_at` and `checked_out_at` are all null.

Adding a line is the operation where the two ledgers of §2.10 actually move. The viewer supplies the `flash_offer_id` and a `qty` between 1 and 20 inclusive; the `cart_id` comes from the path. The gauntlet, in ladder order, is: the acting viewer must own the cart (`ERR_NOT_RESOURCE_OWNER`); the cart must be `OPEN` (`ERR_INVALID_CART_STATE`); the show must be `LIVE` (`ERR_INVALID_SHOW_STATE`) and the named offer must be `ACTIVE` (`ERR_OFFER_NOT_ACTIVE`); the slot's product must be `SUBSTANTIATED` (`ERR_CLAIM_NOT_SUBSTANTIATED`); the logical instant must lie inside the offer's closed window (`ERR_OFFER_WINDOW_CLOSED`); the offer's lineup slot must belong, through its `show_id`, to the same show as the cart (`ERR_OFFER_SHOW_MISMATCH`); the cart must currently hold **fewer than three** lines in state `HELD`, so a fourth distinct line is refused with `ERR_CART_ITEM_LIMIT`; the offer's `remaining_qty` must be at least the requested `qty` (`ERR_OFFER_QTY_EXCEEDED`); and the product's `available_qty` must be at least the requested `qty` (`ERR_INSUFFICIENT_INVENTORY`).

A line that survives all of that is created in state `HELD` with two price snapshots frozen at that instant: `list_unit_price_cents` copies the product's `base_price_cents`, and `offer_unit_price_cents` copies the offer's `offer_price_cents`. The line also copies the offer's slot into its own `lineup_slot_id`, so the product and its cost basis are reachable from the line without traversing the offer, and it records the `cart_id` from the path. `released_reason` and `released_at` are null on a held line.

Pricing then runs in a **pinned four-step order**, and the order matters because the discount looks circular until the order is fixed.

1. The cart's `pre_discount_subtotal_cents` is computed first, from **undiscounted** offer prices: sum, over every line of this cart already in state `HELD`, that line's `offer_unit_price_cents` multiplied by its `qty`, then add the incoming offer's `offer_price_cents` multiplied by the incoming `qty`. Lines in `RELEASED` or `COMMITTED` contribute nothing. Because this subtotal is built from undiscounted prices, it can never depend on the discount it is about to determine.
2. The cart's `bundle_discount_pct` is selected from that subtotal by a two-tier threshold table. A subtotal of at least 150 dollars takes the upper tier of `0.10`; otherwise a subtotal of at least 50 dollars takes the lower tier of `0.05`; otherwise the discount is `0.00`. Both comparisons are inclusive at the floor — a subtotal of exactly 50 dollars is in the lower tier, and exactly 150 dollars is in the upper.
3. The line's `effective_unit_price_cents` is the line's `offer_unit_price_cents` multiplied by one minus `bundle_discount_pct`, rounded half up to a whole cent.
4. The line's `line_gross_cents` is `effective_unit_price_cents` multiplied by `qty`, computed from the already-rounded per-unit figure — no fractional intermediate is carried into this multiplication. The line's `line_tax_cents` is `line_gross_cents` multiplied by a tax rate of 8.75 percent, rounded half up to a whole cent, per line.

Two consequences of that order are load-bearing. The tier is **never** re-derived from the discounted subtotal. And a line, once held, **keeps the effective price it locked at its own add time**: a later add that lifts the cart into a higher tier does not reprice the earlier lines. A cart can therefore legitimately contain two lines of the same product at different `effective_unit_price_cents`.

After the line is priced, both ledgers move inside the same request: the product's `reserved_qty` is increased by the line's `qty` and `available_qty` is recomputed; the offer's `held_qty` is increased by the same `qty` and `remaining_qty` is recomputed; and if `remaining_qty` has reached 0 the offer moves `ACTIVE → EXHAUSTED`. The cart's `pre_discount_subtotal_cents`, `bundle_discount_pct` and `held_item_count` are all refreshed, and the cart's `version` is incremented — which is precisely why a client that has just added a line must re-read the cart before attempting checkout.

### 3.7. Abandonment, Recovery, Checkout and the Order Ledger

Abandonment is the defining loss event of live commerce, and this system treats it as a first-class, *reversible* state rather than as deletion. A cart moves `OPEN → ABANDONED` either by explicit request — available to the owning `Viewer` and to a `MerchandisingManager` working the recovery desk — or by cascade when a show ends. The explicit branch requires only that the cart be `OPEN`; abandoning a cart that is already `ABANDONED`, `CHECKED_OUT` or `EXPIRED` is `ERR_INVALID_CART_STATE`.

The explicit branch does substantial work. Every line still in state `HELD` becomes `RELEASED` with `released_reason` set to `CART_ABANDONED` and `released_at` set to the logical instant. Per released line, the product's `reserved_qty` and the offer's `held_qty` are decremented by that line's `qty`, and `available_qty` and `remaining_qty` are recomputed. Any offer that had been sitting in `EXHAUSTED` and now shows `remaining_qty` of at least 1 transitions `EXHAUSTED → ACTIVE`, provided its window is still open and the show is still `LIVE` — one shopper walking away genuinely reopens the offer for the next one. The cart stamps `abandoned_at` with the logical instant and sets `recovery_deadline_at` to that instant plus a **recovery window of a third of an hour**, meaning 20 minutes. Finally the show's `abandoned_cart_count` is incremented and its `abandonment_rate_bp` recomputed, and the cart's `version` is incremented.

The cascade branch fires during the end-of-broadcast chain of §3.9 and is narrower on purpose. When offer expiry has released the last of a cart's lines, an `OPEN` cart transitions to `ABANDONED` **only if** it held at least one line to begin with and every one of its lines is now in state `RELEASED`. A cart a viewer opened but never added anything to stays `OPEN` — it was never a lost basket. The cascade branch stamps `abandoned_at` and `recovery_deadline_at` the same way, increments the show's `abandoned_cart_count`, recomputes `abandonment_rate_bp`, and increments the cart's `version`; it does not itself release lines, because the offer expiry already did.

Recovery reverses abandonment and is the operation with the subtlest arithmetic in the system. It is available to the owning viewer and to a `MerchandisingManager`, and requires that the cart be `ABANDONED` (`ERR_INVALID_CART_STATE`), that the logical instant be **strictly before** `recovery_deadline_at` — an attempt landing exactly on the deadline is already too late and is refused with `ERR_RECOVERY_WINDOW_CLOSED` — and that at least one line still be recoverable. A released line is recoverable when the offer it names is currently `ACTIVE`, that offer's `remaining_qty` is at least the line's `qty`, and the product's `available_qty` is at least the line's `qty`. If no line satisfies all three tests, recovery is refused with `ERR_NO_RECOVERABLE_ITEMS`; the same allotment and inventory ceilings of §2.10 bound what a re-hold may take, and a re-hold may never breach them.

Recovery processes the eligible lines in **ascending `created_at` order**, and each line is re-priced as it is re-held: the line returns to state `HELD` with `released_reason` and `released_at` cleared, and its `effective_unit_price_cents`, `line_gross_cents` and `line_tax_cents` are re-locked at the **current** bundle tier using the same pinned four-step procedure of §3.6. Because the subtotal that selects the tier counts only the lines already re-held plus the line being re-held, an early line can land in a lower tier than it originally enjoyed and a late line in a higher one — a recovered cart may legitimately price a line differently than it did before abandonment. Lines that fail the eligibility test stay `RELEASED` and are simply left behind.

Per re-held line, the product's `reserved_qty` and the offer's `held_qty` are incremented and `available_qty` and `remaining_qty` recomputed; any offer whose `remaining_qty` reaches 0 in the process transitions `ACTIVE → EXHAUSTED`. The cart's `recovered_count` is incremented by one, `abandoned_at` and `recovery_deadline_at` are cleared back to null, the show's `abandoned_cart_count` is decremented and `abandonment_rate_bp` recomputed, and the cart's `version` is incremented. A cart may be abandoned and recovered repeatedly — `recovered_count` is the running tally of that `OPEN → ABANDONED → OPEN` loop.

Checkout converts the basket. Only the owning viewer may check out, and the request carries `expected_cart_version` as its sole payload field. In ladder order, the checks are: ownership, then request shape, then the stale-version comparison of §2.8 (`ERR_STALE_CART_VERSION`), then that the cart is `OPEN` (`ERR_INVALID_CART_STATE`), then that the show is `LIVE` (`ERR_INVALID_SHOW_STATE`), then that at least one line is in state `HELD` (`ERR_EMPTY_CART`). A cart whose lines were all released by an offer expiry is empty for this purpose even though the rows still exist.

Checkout moves every `HELD` line of the cart to state `COMMITTED` and shifts both ledgers **sideways rather than down**. Per committed line, the product's `reserved_qty` is decreased by that line's `qty` and its `committed_qty` increased by the same amount — so `available_qty` is unchanged, because the units were already out of circulation. Likewise the offer's `held_qty` is decreased and its `sold_qty` increased by that `qty`, leaving `remaining_qty` unchanged. The cart stamps `checked_out_at` with the logical instant, recomputes `held_item_count` and `pre_discount_subtotal_cents`, increments its `version`, and moves `OPEN → CHECKED_OUT`. The show's `abandonment_rate_bp` is recomputed as well, because the denominator of that rate counts every cart the show ever produced, not only the lost ones.

An `Order` is created in the same request, over exactly the lines checkout has just committed. `cart_id`, `show_id` and `viewer_id` are copied from the cart. Four monetary fields are computed in this order. `merchandise_cents` is the sum of `line_gross_cents` across the committed lines. `tax_cents` is the sum, across those same lines, of each line's gross multiplied by the 8.75 percent tax rate and rounded half up **per line** — the per-line rounded taxes are then added, and summing the gross first and taxing once is explicitly not the rule. `shipping_cents` is a flat 5.99 dollars, except that it is zero when `merchandise_cents` reaches at least 75 dollars; a merchandise total of exactly 75 dollars ships free. `total_cents` is `merchandise_cents` plus `tax_cents` plus `shipping_cents`. Lines in state `RELEASED` are excluded from every term. The new order enters with `payment_state` of `AUTHORIZED` and `fulfillment_state` of `PENDING`, `host_commission_accrued_cents` and `refunded_cents` at 0, and `captured_at`, `cancelled_at` and `cancel_reason` null.

Capture is a `MerchandisingManager` act and is permitted while the show is `LIVE` or `ENDED` — money can be taken after the broadcast closes but not after sign-off. It requires `payment_state` to be `AUTHORIZED` (`ERR_INVALID_ORDER_STATE`) and the show to be in one of those two statuses (`ERR_INVALID_SHOW_STATE`). Capture moves **both** dimensions: `payment_state` goes `AUTHORIZED → CAPTURED` with `captured_at` stamped at the logical instant, and `fulfillment_state` goes `PENDING → ALLOCATED`, leaving the order `CAPTURED` on the payment dimension and `ALLOCATED` on the fulfilment dimension. It stamps `host_commission_accrued_cents` as the order's `merchandise_cents` multiplied by the `commission_pct` of the host holding this show's `PRIMARY` booking, rounded half up to a whole cent. The show's `gross_merchandise_cents` — the sum of `merchandise_cents` across this show's orders whose `payment_state` is `CAPTURED` — and its `margin_provisional_cents` are both recomputed, and the order's `version` is incremented.

Cancellation is available to a `MerchandisingManager` and to the owning viewer, requires a `cancel_reason`, and has **two branches with deliberately divergent effects**. Both branches stamp `cancelled_at` and `cancel_reason`, move `fulfillment_state` to `CANCELLED`, release every `COMMITTED` line of the order's cart to `RELEASED` with `released_reason` set to `ORDER_CANCELLED`, decrement the product's `committed_qty` and the offer's `sold_qty` by each released `qty` while recomputing `available_qty` and `remaining_qty`, restock any offer that was `EXHAUSTED` and now shows `remaining_qty` of at least 1 back to `ACTIVE` when its window is still open and the show is still `LIVE`, and increment the order's `version`.

They diverge on money. A never-captured order — `payment_state` of `AUTHORIZED` — moves `AUTHORIZED → VOIDED`, its `fulfillment_state` moving `PENDING → CANCELLED`; `refunded_cents` stays 0, and the show's `gross_merchandise_cents` is **unchanged**, because a never-captured order was never inside that figure. A captured order moves `CAPTURED → REFUNDED`, its `fulfillment_state` moving `ALLOCATED → CANCELLED`; `refunded_cents` is set to the order's `total_cents`, `host_commission_accrued_cents` is reset to 0, and the show's `gross_merchandise_cents` and `margin_provisional_cents` are both recomputed, because the refunded order leaves both aggregates. Cancelling an order already `VOIDED` or `REFUNDED` is `ERR_INVALID_ORDER_STATE`.

The show's `abandonment_rate_bp` deserves its own statement, since three different operations recompute it. It is 10,000 multiplied by `abandoned_cart_count`, divided by the total number of carts ever opened on the show, rounded half up to a whole basis point; when the show has no carts at all the rate is 0. `abandoned_cart_count` counts the show's carts whose status is `ABANDONED` or `EXPIRED`.

### 3.8. The Interactive Layer: Chat Moderation, Question Routing and Polls

Shoppers are registered by a `PlatformAdmin` with a `display_name` used in chat and an `email` used for abandonment-recovery outreach; the address must be unique across all viewers, and a duplicate is `ERR_INVALID_REQUEST`. A new viewer starts with `chat_status` of `ACTIVE`, `strike_count` at 0 and `muted_until` null.

Three kinds of interaction share one resource and one submission operation, distinguished by `kind`. A `Viewer` submits a `CHAT` or a `QUESTION`, supplying the `show_id` and the `body` text; the server takes `viewer_id` from `X-User-ID`, leaves `host_id` null, and places the interaction in `PENDING_MODERATION`. A `Host` submits a `POLL`, supplying the `show_id`, the poll prompt as `body`, and an `options` array of between two and four option labels; the server takes `host_id` from `X-User-ID`, leaves `viewer_id` null, initialises `tallies` to a map from each option's index — rendered as a string — to a count of zero, initialises `voted_viewer_ids` to an empty list and `vote_count` to 0, and places the poll directly in `OPEN`. The `options` array is required when `kind` is `POLL` and forbidden otherwise; a poll with one option or five options, or a chat message carrying options, is `ERR_INVALID_REQUEST`. Submission of any kind requires the show to be `LIVE` (`ERR_INVALID_SHOW_STATE`).

Muting gates submission and voting alike. An acting viewer must have `chat_status` of `ACTIVE`, or else a `muted_until` at or before the logical instant — in which case the mute has lapsed, the viewer is **auto-unmuted** back to `ACTIVE` on that first submission issued at or after `muted_until`, and the request proceeds. A viewer whose `chat_status` is `MUTED` and whose `muted_until` is strictly later than the logical instant is refused with `ERR_VIEWER_MUTED`.

Moderation is exclusively a `Moderator` duty and carries an `action` of either `APPROVE` or `BLOCK` plus an optional `blocked_reason`. Only interactions in `PENDING_MODERATION` may be moderated — an interaction already `APPROVED`, already `BLOCKED`, already `QUEUED`, or in any other state is `ERR_INVALID_INTERACTION_STATE` — and only `CHAT` and `QUESTION` kinds are moderatable at all. The approve action forks on kind, and the two branches are not interchangeable. Approving a `CHAT` moves it `PENDING_MODERATION → APPROVED`, stamps `moderated_at` with the logical instant and increments `version`: the message is published and the story ends. Approving a `QUESTION` moves it `PENDING_MODERATION → QUEUED`, stamps `moderated_at`, increments the show's `pending_question_count` by one, and increments `version`: the question now sits in the host's queue awaiting routing.

Blocking is the deepest cascade in the interactive layer, five links long, and every link fires inside the one moderation request. First, the interaction moves `PENDING_MODERATION → BLOCKED` with the supplied `blocked_reason` and `moderated_at` recorded. Second, because the block happened, the `strike_count` of the viewer named by that interaction's `viewer_id` is incremented by one — that field is the running count of this viewer's interactions that have reached `BLOCKED`. Third, because the increment happened, a `strike_count` that has now reached **two or more** flips that viewer's `chat_status` from `ACTIVE` to `MUTED` and sets `muted_until` to the logical instant plus a quarter of an hour, meaning 15 minutes. Fourth, because the mute happened, every *other* interaction belonging to that viewer whose state is `PENDING_MODERATION`, `QUEUED`, `ROUTED` or `DEFERRED` is set to `WITHDRAWN`, each with its own `version` incremented — a muted viewer's whole pipeline is cleared, not merely their next message. Fifth, each withdrawn interaction whose `kind` is `QUESTION` causes the show's `pending_question_count` to be recomputed. The withdrawal branch out of `PENDING_MODERATION` only increments `version`, since a question not yet approved was never counted; the withdrawal branches out of `QUEUED`, `ROUTED` and `DEFERRED` each recompute `pending_question_count` as well as incrementing `version`. `Show.pending_question_count` is always the count of that show's interactions whose `kind` is `QUESTION` and whose state is `QUEUED`, `ROUTED` or `DEFERRED`.

Routing hands a queued question to the presenter and is likewise a `Moderator` act. It requires the interaction to be `QUEUED`, its `kind` to be `QUESTION`, and the show to be `LIVE` (`ERR_INVALID_SHOW_STATE`); anything else is `ERR_INVALID_INTERACTION_STATE`. Routing moves the question `QUEUED → ROUTED`, stamps `routed_at` with the logical instant, and increments `version`.

Host actions are the presenter's three levers, selected by an `action` of `ANSWER`, `DEFER` or `CLOSE_POLL`. Answering and deferring both require the acting host's `X-User-ID` to equal the `host_id` of the show's `PRIMARY` booking whose status is `CONFIRMED`, or the request is `ERR_NOT_RESOURCE_OWNER` — guest hosts do not field routed questions. Answering requires the question to be `ROUTED`, moves it `ROUTED → ANSWERED`, records the supplied `answer_body`, stamps `answered_at` with the logical instant, decrements the show's `pending_question_count` by one, and increments `version`.

Deferring is a bounded loop, and its behaviour inside a single request is precisely specified. The question must be `ROUTED`, and its `defer_count` must be **strictly less than two**; a deferral attempted when `defer_count` already equals 2 is refused with `ERR_DEFERRAL_LIMIT_REACHED`, the question stays `ROUTED`, and the host's only remaining option is to answer it. An accepted deferral moves the question `ROUTED → DEFERRED`, increments `defer_count` by one and increments `version`; then, unconditionally and in the same request, the question moves `DEFERRED → QUEUED` with `routed_at` cleared to null and `version` incremented a second time. A single deferral request therefore returns a question in state `QUEUED`, with `defer_count` one higher than before and `version` **two** higher than before. This closes the `QUEUED → ROUTED → DEFERRED → QUEUED` cycle, and the cycle terminates because the third deferral is refused.

Closing a poll is the third lever. It requires the interaction's `kind` to be `POLL`, its state to be `OPEN`, and the acting host's `X-User-ID` to equal that interaction's own `host_id` (`ERR_NOT_RESOURCE_OWNER`) — a poll is closed by the host who opened it, not by the show's primary host. Closing moves the poll `OPEN → CLOSED`, freezes `tallies` and `vote_count`, and increments `version`. A `CLOSE_POLL` action aimed at a `CHAT` or a `QUESTION`, or an `ANSWER` or `DEFER` aimed at anything not `ROUTED`, is a kind/action mismatch and is refused with `ERR_INVALID_INTERACTION_STATE`.

Voting is a `Viewer` act carrying a single `option_index`. Votes are accepted only while the poll is `OPEN`: a vote against a `CLOSED` poll, or against an interaction whose `kind` is not `POLL`, is `ERR_POLL_NOT_OPEN`. A viewer votes at most once per poll — if the acting `X-User-ID` is already present in `voted_viewer_ids` the vote is refused with `ERR_DUPLICATE_VOTE`. An `option_index` outside the range of the poll's `options` array is `ERR_INVALID_REQUEST`. A valid vote increments the `tallies` entry for that index and increments `vote_count`, appends the acting `X-User-ID` to `voted_viewer_ids`, and increments the interaction's `version`. `vote_count` is always the sum of the values in `tallies`.

### 3.9. Ending the Broadcast, Replay Merchandising, Settlement and Analytics

Ending a broadcast is a producer's single request with the widest blast radius in the system, and it runs four links deep. The show must be `LIVE` (`ERR_INVALID_SHOW_STATE`). It moves `LIVE → ENDED`, stamps `ended_at` with the logical instant — the zero point of the replay decay curve — and increments `version`. Alongside, every simulcast destination of the show still in `LIVE` transitions `LIVE → ENDED`, and every booking of the show still in `CONFIRMED` transitions `CONFIRMED → COMPLETED`, each with its own `version` incremented.

Then the release chain fires. Link one: every flash offer of this show whose status is `SCHEDULED`, `ACTIVE` or `EXHAUSTED` transitions to `EXPIRED`. Link two: each expiring offer releases every cart line of that offer still in state `HELD`, setting `state` to `RELEASED` and `released_reason` to `OFFER_EXPIRED`; and per released line the product's `reserved_qty` is decremented, `available_qty` recomputed, and the offer's `held_qty` decremented. Link three: any cart still `OPEN` that held at least one line and whose lines are now **all** in state `RELEASED` transitions `OPEN → ABANDONED`, stamping `abandoned_at` at the logical instant and `recovery_deadline_at` 20 minutes later. Link four: each such abandonment increments the show's `abandoned_cart_count` and its `abandonment_rate_bp` is recomputed. Finally the show recomputes `margin_provisional_cents` and `pending_question_count`. Shoppers therefore retain a 20-minute post-show recovery window on the baskets the ending itself abandoned.

Replay merchandising begins once the broadcast is off air, and all three of its operations are refused while the show is still `DRAFT`, `READY` or `LIVE`, with `ERR_SHOW_NOT_ENDED`. A `MerchandisingManager` first anchors a time-stamped product link on a lineup slot by supplying `marker_offset_sec`, the number of seconds from the replay's start at which the link appears, and `product_link_url`, the deep link itself. The offset must land inside the material that actually aired: at least 0 and no more than the whole number of seconds between the show's `went_live_at` and its `ended_at`, truncated downwards. An offset outside that range is `ERR_MARKER_OFFSET_OUT_OF_RANGE`. A successful call writes `replay_marker_offset_sec` and `replay_product_link_url`, sets `replay_marker_status` from `NONE` to `DRAFT`, and increments the slot's `version`. Publishing then moves `replay_marker_status` from `DRAFT` to `PUBLISHED` and increments `version` again; only a published marker earns attribution.

Post-show conversions are recorded one at a time against a slot, each carrying the `viewer_id` who converted, the `net_revenue_cents` of that conversion, and the `occurred_at` instant it happened. The slot's `replay_marker_status` must be `PUBLISHED`, or the conversion is refused with `ERR_REPLAY_MARKER_NOT_PUBLISHED`, and `occurred_at` must be at or after the show's `ended_at`, or the conversion is `ERR_INVALID_REQUEST`.

Attribution decays in three steps. Take the elapsed time from the show's `ended_at` to the conversion's `occurred_at` and truncate it downwards to a whole number of hours. Within the first day — an elapsed figure of 24 hours or fewer — the conversion carries full weight of `1.0`. Beyond that but within two days — 48 hours or fewer — it carries `0.6`. Beyond that but within three days — 72 hours or fewer — it carries `0.3`. Anything later carries `0.0`. The boundaries are inclusive, so exactly 24 hours still weights `1.0`, exactly 48 weights `0.6`, exactly 72 weights `0.3`, and 73 hours weights `0.0`. The slot's `replay_attributed_revenue_cents` is increased by `net_revenue_cents` multiplied by that weight, rounded half up to a whole cent **per conversion** before it is added to the running total. The slot's `replay_conversions_count` is incremented by one **even when the weight is zero** — a conversion outside the attribution horizon is still a conversion and still counts toward the host's attributed score. The show's `replay_attributed_revenue_cents` is then recomputed as the sum of `replay_attributed_revenue_cents` across all of that show's slots, and the slot's `version` is incremented.

Settlement is the `ComplianceOfficer`'s final act, moving the show `ENDED → SETTLED` with an optional `attestation_note`. Three conditions are checked, in ladder order: the show must be `ENDED` (`ERR_INVALID_SHOW_STATE`); **no order of the show may still be sitting in `payment_state` of `AUTHORIZED`** — every order must have been captured, voided or refunded, and an outstanding authorisation blocks sign-off with `ERR_INVALID_ORDER_STATE`; and the segregation-of-duties comparison of §2.12 must pass (`ERR_SEGREGATION_OF_DUTIES`). Sign-off stamps `settled_at` with the logical instant and `compliance_signoff_by_user_id` with the officer's `X-User-ID`, computes and stamps `margin_final_cents`, transitions every cart of the show that is `ABANDONED` and whose `recovery_deadline_at` is at or before the logical instant `ABANDONED → EXPIRED` (each with `version` incremented), recomputes `abandoned_cart_count` and `abandonment_rate_bp`, and increments the show's `version`.

Margin analysis exists in **two variants of the same computation**, and the gap between them is the point of the exercise. Both are available as a computed read that echoes the `show_id` and the `variant` requested; `variant` defaults to `PROVISIONAL` when omitted, and requesting the provisional variant stamps its result into `Show.margin_provisional_cents` as a side effect. The read also reports `order_count` — the number of orders inside the variant's revenue scope — plus `merchandise_revenue_cents`, `cogs_cents`, `return_provision_cents`, `host_commission_cents` and `margin_cents`, alongside the show's current `gross_merchandise_cents`, `abandoned_cart_count`, `abandonment_rate_bp` and `replay_attributed_revenue_cents`.

The **provisional** variant is the in-flight view. `merchandise_revenue_cents` is the sum of `merchandise_cents` across this show's orders whose `payment_state` is `AUTHORIZED` or `CAPTURED` and whose `fulfillment_state` is not `CANCELLED`. `cogs_cents` is the sum, over the `COMMITTED` cart lines belonging to the carts of those orders, of the line's lineup slot `unit_cost_snapshot_cents` multiplied by the line's `qty` — the cost frozen when the slot was created. `host_commission_cents` is `merchandise_revenue_cents` multiplied by the primary host's `commission_pct`, rounded half up. `return_provision_cents` is 0. `margin_cents` is `merchandise_revenue_cents` less `cogs_cents` less `host_commission_cents`. The provisional variant is recomputed and stamped on the end-of-broadcast transition and on every order capture and refund, and it applies while the show is `LIVE` or `ENDED`.

The **final** variant is the settled view, computed on the sign-off transition and available on demand by requesting `FINAL`. It differs in four ways, and the evaluation order among them is pinned. `merchandise_revenue_cents` counts only orders whose `payment_state` is `CAPTURED` and whose `fulfillment_state` is not `CANCELLED` — still-authorised revenue is dropped. `cogs_cents` revalues the same committed lines at the product's **current** `unit_cost_cents` rather than at the slot snapshot, which is why a post-show cost revision moves the final margin and not the provisional one. Next, `net_of_returns_cents` is `merchandise_revenue_cents` multiplied by one minus a return provision of 6 percent, rounded half up to a whole cent, and `return_provision_cents` is `merchandise_revenue_cents` minus that rounded `net_of_returns_cents`. Then `host_commission_cents` is the **rounded** `net_of_returns_cents` multiplied by the primary host's `commission_pct`, rounded half up — commission is never taken on the unrounded product. Finally `margin_cents` is `net_of_returns_cents` less `cogs_cents` less `host_commission_cents`. Because the provisional variant counts unsettled revenue, values cost at the older snapshot, and takes no return provision, it reports a higher margin than the final variant for identical data.

In both variants the primary host is the host of this show's booking whose `role` is `PRIMARY` and whose status is `CONFIRMED` or `COMPLETED`. When the show has no such booking, commission is 0.

Host effectiveness is the second two-variant computation, available as a computed read that echoes the `host_id` and the `variant`. Scope is the set of shows on which this host holds a `PRIMARY` booking whose status is `CONFIRMED` or `COMPLETED`, narrowed to a single show when the optional `show_id` field is supplied. Seven raw quantities are gathered over that scope. `live_orders_count` is the number of orders whose `payment_state` is `AUTHORIZED` or `CAPTURED` and whose `fulfillment_state` is not `CANCELLED`. `unique_cart_count` is the number of carts ever opened on those shows, counted in every status. `replay_conversions_count` is the sum of `replay_conversions_count` across those shows' lineup slots. `answered_questions_count` is the number of interactions whose `kind` is `QUESTION` and whose state is `ANSWERED`. `poll_votes_count` is the sum of `vote_count` across the poll interactions in scope. `late_ack_count` is the number of disclosure records in scope whose `acknowledged_late` flag is true. And an unsubstantiated-claim indicator is 1 when any product merchandised in scope has `claim_substantiation_status` other than `SUBSTANTIATED`, and 0 otherwise.

Those quantities feed three components, each an integer from 0 to 100. The `conversion_component` divides the effective order count by the larger of `unique_cart_count` and 1, multiplies by 100, rounds half up, and caps the result at 100. The `engagement_component` awards 10 points per answered question and 2 points per poll vote, capped at 100. The `compliance_component` starts at 100, subtracts 25 points for each late disclosure acknowledgement and a further 50 points if the unsubstantiated-claim indicator is 1, and floors the result at 0. The `effectiveness_score` is then the weighted sum of the three — the conversion component at a weight of `0.5`, the engagement component at `0.3`, and the compliance component at `0.2` — rounded half up exactly once at the end.

The two variants differ only in the effective order count feeding the conversion component. The `LIVE_WINDOW` variant, which applies when `variant` is omitted or equals `LIVE_WINDOW`, uses `live_orders_count` alone and ignores replay conversions entirely. The `ATTRIBUTED_72H` variant adds half an order for each replay conversion: the effective count is `live_orders_count` plus `replay_conversions_count` multiplied by `0.5`. For identical data the attributed variant therefore yields a score greater than or equal to the live-window variant, never lower. Requesting the live-window variant stamps its result into the host's `effectiveness_score_live`; requesting the attributed variant stamps it into `effectiveness_score_attributed`. Both fields start at 0 on a newly registered host and hold the most recent value computed for that variant.

## 4. Endpoint Definitions

Operations that bring a new stand-alone resource into existence return `201 Created`. Operations that modify an existing resource — including every state transition, every ledger movement and every computed read that stamps a score back onto its subject — return `200 OK`. Two cases are worth flagging because their names suggest otherwise: in-stream checkout returns `201 Created`, because its product is a new `Order` rather than a modified cart, and recording a replay conversion returns `201 Created`, because each call registers a new conversion event even though the response body is the updated lineup slot. Where a role column reads "All seven roles", it means `ShowProducer`, `MerchandisingManager`, `ComplianceOfficer`, `Moderator`, `Host`, `Viewer` and `PlatformAdmin` without exception.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Sets the server's logical clock; reports the new and previous instants | PlatformAdmin |
| POST | `/hosts` | Registers on-air talent | ShowProducer, PlatformAdmin |
| GET | `/hosts/{host_id}` | Reads one host, with certification status recomputed against the logical clock | All seven roles |
| POST | `/hosts/{host_id}/disclosure-certifications` | Records or renews the host's paid-endorsement disclosure certification | ComplianceOfficer |
| GET | `/hosts/{host_id}/performance` | Computed read: host effectiveness score, in the requested variant | ShowProducer, MerchandisingManager, PlatformAdmin |
| POST | `/products` | Creates a merchandisable product with its on-hand inventory | MerchandisingManager |
| GET | `/products/{product_id}` | Reads one product including the reconciled inventory pool | All seven roles |
| POST | `/products/{product_id}/inventory-adjustments` | Adjusts on-hand units and/or revises the landed unit cost | MerchandisingManager |
| POST | `/products/{product_id}/claim-substantiations` | Records a compliance decision on the product's on-air claim | ComplianceOfficer |
| POST | `/viewers` | Registers a shopping viewer | PlatformAdmin |
| GET | `/viewers/{viewer_id}` | Reads one viewer including moderation strikes and mute window | All seven roles |
| POST | `/shows` | Creates a show on the broadcast calendar in DRAFT | ShowProducer |
| GET | `/shows/{show_id}` | Reads one show with every derived counter and margin field | All seven roles |
| POST | `/shows/{show_id}/ready` | Runs the readiness gate and takes the show from DRAFT to READY | ShowProducer |
| POST | `/shows/{show_id}/go-live` | Takes the show from READY to LIVE and takes every provisioned destination live | ShowProducer |
| POST | `/shows/{show_id}/end` | Ends the broadcast and runs the release cascade | ShowProducer |
| POST | `/shows/{show_id}/compliance-signoff` | Compliance sign-off; settles the show, stamps the final margin and expires stale abandoned carts | ComplianceOfficer |
| GET | `/shows/{show_id}/analytics` | Computed read: show margin analysis, in the requested variant | ShowProducer, MerchandisingManager, PlatformAdmin |
| POST | `/stream-channels` | Adds a simulcast destination to a show in DRAFT | ShowProducer |
| GET | `/stream-channels/{channel_id}` | One simulcast destination with its latest health metrics and readiness index | All seven roles |
| GET | `/stream-channels` | Reverse lookup: filterable list of simulcast destinations | All seven roles |
| POST | `/stream-channels/{channel_id}/provision` | Provisions, or re-provisions after a failure, the destination | ShowProducer |
| POST | `/stream-channels/{channel_id}/health-reports` | Reports latency and dropped frames; recomputes readiness and can fail the destination | ShowProducer, PlatformAdmin |
| POST | `/host-bookings` | Books a host onto a show for a call-time interval | ShowProducer |
| GET | `/host-bookings/{booking_id}` | Reads one booking | All seven roles |
| GET | `/host-bookings` | Reverse lookup: bookings filtered by show, host and/or status | All seven roles |
| POST | `/host-bookings/{booking_id}/confirm` | The booked host accepts the booking | Host |
| POST | `/host-bookings/{booking_id}/cancel` | Cancels a booking; a cancelled primary booking reverts a READY show | ShowProducer, Host |
| POST | `/lineup-slots` | Adds a product segment to a show's lineup and snapshots the unit cost | MerchandisingManager |
| GET | `/lineup-slots/{slot_id}` | Reads one lineup slot including replay-marker and attribution fields | All seven roles |
| GET | `/lineup-slots` | Reverse lookup: slots filtered by show and/or product | All seven roles |
| POST | `/lineup-slots/{slot_id}/replay-marker` | Sets the time-stamped replay product link on the slot | MerchandisingManager |
| POST | `/lineup-slots/{slot_id}/replay-marker/publish` | Publishes the replay marker | MerchandisingManager |
| POST | `/lineup-slots/{slot_id}/replay-conversions` | Records one decay-weighted post-show conversion against the slot's published marker | MerchandisingManager |
| POST | `/flash-offers` | Creates a flash offer against a lineup slot, superseding any scheduled offer on that slot | MerchandisingManager |
| GET | `/flash-offers/{offer_id}` | Reads one offer with the reconciled allotment ledger | All seven roles |
| GET | `/flash-offers` | Reverse lookup: offers filtered by slot, superseding offer and/or status | All seven roles |
| POST | `/flash-offers/{offer_id}/activate` | Opens the offer for in-stream purchase | MerchandisingManager |
| POST | `/disclosure-records` | Registers a required on-air disclosure for a booking | ShowProducer |
| GET | `/disclosure-records/{record_id}` | Reads one disclosure record | All seven roles |
| GET | `/disclosure-records` | Reverse lookup: disclosures filtered by show, booking and/or status | All seven roles |
| POST | `/disclosure-records/{record_id}/acknowledge` | The booked host acknowledges the approved script verbatim | Host |
| POST | `/carts` | Opens a persistent cart for the acting viewer on one show | Viewer |
| GET | `/carts/{cart_id}` | Reads one cart including the pre-discount subtotal and current bundle tier | All seven roles |
| GET | `/carts` | Reverse lookup: carts filtered by show, viewer and/or status — the recovery worklist | ShowProducer, MerchandisingManager, ComplianceOfficer, Viewer, PlatformAdmin |
| POST | `/carts/{cart_id}/items` | Adds a flash-offer line, locking the effective unit price and holding allotment and inventory | Viewer |
| POST | `/carts/{cart_id}/abandon` | Marks the cart abandoned, releasing every hold and opening the recovery window | Viewer, MerchandisingManager |
| POST | `/carts/{cart_id}/recover` | Re-holds every still-eligible released line at the current bundle tier and reopens the cart | Viewer, MerchandisingManager |
| POST | `/carts/{cart_id}/checkout` | In-stream checkout; commits the holds and creates the order | Viewer |
| GET | `/cart-items/{item_id}` | Reads one cart line with its locked pricing and hold state | All seven roles |
| GET | `/cart-items` | Reverse lookup: lines filtered by cart, offer, slot and/or state | All seven roles |
| GET | `/orders/{order_id}` | Reads one order with both state dimensions and every monetary field | All seven roles |
| GET | `/orders` | Reverse lookup: orders filtered by cart, show, viewer and/or payment state | ShowProducer, MerchandisingManager, ComplianceOfficer, Viewer, PlatformAdmin |
| POST | `/orders/{order_id}/capture` | Captures payment and allocates fulfilment; accrues host commission | MerchandisingManager |
| POST | `/orders/{order_id}/cancel` | Cancels the order; voids or refunds it and returns allotment and inventory | MerchandisingManager, Viewer |
| POST | `/interactions` | Submits a viewer chat or question, or opens a host poll | Viewer, Host |
| GET | `/interactions/{interaction_id}` | Reads one interaction with its moderation/routing state and poll tallies | All seven roles |
| GET | `/interactions` | Reverse lookup: interactions filtered by show, viewer, host, kind and/or state | All seven roles |
| POST | `/interactions/{interaction_id}/moderate` | Moderator decision on a chat or question: approve or block | Moderator |
| POST | `/interactions/{interaction_id}/route` | Routes a queued question to the on-air host | Moderator |
| POST | `/interactions/{interaction_id}/host-action` | Host action: answer or defer a routed question, or close an open poll | Host |
| POST | `/interactions/{interaction_id}/votes` | Casts the acting viewer's single vote on an open poll | Viewer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_HOST_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_VIEWER_NOT_FOUND` | 404 Not Found |
| `ERR_SHOW_NOT_FOUND` | 404 Not Found |
| `ERR_STREAM_CHANNEL_NOT_FOUND` | 404 Not Found |
| `ERR_HOST_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_LINEUP_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_FLASH_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_DISCLOSURE_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_CART_NOT_FOUND` | 404 Not Found |
| `ERR_CART_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INTERACTION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_LINEUP_SLOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CART_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_SHOW_STATE` | 409 Conflict |
| `ERR_INVALID_BOOKING_STATE` | 409 Conflict |
| `ERR_INVALID_CHANNEL_STATE` | 409 Conflict |
| `ERR_INVALID_DISCLOSURE_STATE` | 409 Conflict |
| `ERR_INVALID_OFFER_STATE` | 409 Conflict |
| `ERR_INVALID_CART_STATE` | 409 Conflict |
| `ERR_INVALID_ORDER_STATE` | 409 Conflict |
| `ERR_INVALID_INTERACTION_STATE` | 409 Conflict |
| `ERR_OFFER_NOT_ACTIVE` | 409 Conflict |
| `ERR_SHOW_NOT_ENDED` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBSTANTIATED` | 422 Unprocessable Entity |
| `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` | 422 Unprocessable Entity |
| `ERR_HOST_CERTIFICATION_EXPIRED` | 422 Unprocessable Entity |
| `ERR_HOST_BOOKING_OVERLAP` | 409 Conflict |
| `ERR_OFFER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_OFFER_WINDOW_CLOSED` | 409 Conflict |
| `ERR_GO_LIVE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_RECOVERY_WINDOW_CLOSED` | 409 Conflict |
| `ERR_OFFER_SHOW_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PRIMARY_HOST_CONFLICT` | 409 Conflict |
| `ERR_PRIMARY_HOST_MISSING` | 422 Unprocessable Entity |
| `ERR_LINEUP_EMPTY` | 422 Unprocessable Entity |
| `ERR_SIMULCAST_NOT_READY` | 422 Unprocessable Entity |
| `ERR_VIEWER_MUTED` | 403 Forbidden |
| `ERR_POLL_NOT_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_VOTE` | 409 Conflict |
| `ERR_DEFERRAL_LIMIT_REACHED` | 409 Conflict |
| `ERR_REPLAY_MARKER_NOT_PUBLISHED` | 409 Conflict |
| `ERR_MARKER_OFFSET_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_EMPTY_CART` | 422 Unprocessable Entity |
| `ERR_NO_RECOVERABLE_ITEMS` | 409 Conflict |
| `ERR_CART_ITEM_LIMIT` | 422 Unprocessable Entity |
| `ERR_OFFER_QTY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_INVENTORY` | 422 Unprocessable Entity |
