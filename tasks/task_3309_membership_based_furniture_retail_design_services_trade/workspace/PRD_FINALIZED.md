# Membership-Based Furniture Retail, Design Services & Trade Program API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for a membership-based furniture retail platform operating a gallery network with limited on-hand inventory, custom upholstery production, white-glove delivery from owned hubs, complimentary interior design services, and a credentialed trade program for professional designers. The business sells the majority of its product to order rather than from stock: customers place orders that begin as quotes, custom and special-order pieces enter a production schedule after a non-cancelable deposit is captured, and completed orders are delivered through hub-managed routes that include room-of-choice placement, assembly, and packaging removal.

The system's commercial engine rests on three pricing tracks that share one catalog: enrolled members pay an annual fee of $175.00 and receive discounted pricing across all product lines; verified trade accounts receive deeper, tier-based discounts under separate terms; and retail guests pay list price. Membership carries renewal, grace, lapse, and cancellation mechanics with a defined refund window, and member standing at calculation time — not at order creation — governs what a customer is charged. Marketing runs through periodic source book editions whose release activates promotional pricing on a designated set of products, with a fixed print-to-release lead time. Because many of these rules interact (a member lapsing mid-quote, a source book releasing between quote and confirm, a custom line locking its deposit once production begins), the platform pins every evaluation order, rounding step, and cascade described below so that any two implementations of this document produce identical numbers.

All scheduling, expiry, and release behavior is driven by a server-maintained logical clock rather than the host wall clock, so that the entire temporal surface of the system is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts — identity, envelope, pagination, resource shape, clock semantics, money handling, pricing tracks, concurrency control, and validation ordering — that apply uniformly to every endpoint in §4.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the operational capacity. A request missing either header, or presenting a role name outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorized for the target endpoint, or whose identity fails an ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes eight roles, spelled exactly: `Anonymous`, `Member`, `TradeDesigner`, `GalleryAssociate`, `TradeReviewer`, `ProductionPlanner`, `HubOperator`, and `PlatformAdmin`.

Two roles are **entity-backed**, meaning `X-User-ID` must equal the `id` of a persisted entity and ownership checks compare resource foreign keys against it:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` — an order's `member_id`, a consultation's `member_id`, or the member attached to the order underlying a return — compare that field to `X-User-ID`.
- When `X-User-Role` is `TradeDesigner`, `X-User-ID` is the `id` of the acting `TradeAccount`; ownership checks on trade orders compare the order's `trade_account_id` to `X-User-ID`.

The remaining six roles are **opaque**: `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. Specifically:

- When `X-User-Role` is `Anonymous`, the caller is an unauthenticated-enrollment principal (the role header is present but no entity exists yet); this role may only enroll members, apply for trade accounts, and read products.
- When `X-User-Role` is `GalleryAssociate`, the caller is gallery staff acting on behalf of any customer, with no ownership restriction.
- When `X-User-Role` is `TradeReviewer`, the caller reviews trade program credentials.
- When `X-User-Role` is `ProductionPlanner`, the caller schedules custom upholstery production.
- When `X-User-Role` is `HubOperator`, the caller runs white-glove delivery routes from an owned hub.
- When `X-User-Role` is `PlatformAdmin`, the caller administers galleries, products, source books, and the test-driving ops and clock endpoints.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order.

List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, in addition to the standard request metadata fields.

### 2.4. Common Resource Properties

Every primary resource in the system — Member, TradeAccount, Gallery, Product, SourceBook, Order, OrderLine, ProductionSlot, DesignConsultation, DeliveryAppointment, and ReturnRequest — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, unique within the resource's collection.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by exactly 1 on every mutation. Any cascade, bubble-up, or scheduled-cycle effect that changes a resource's stored fields counts as a mutation of that resource and therefore refreshes its `updated_at` and bumps its `version`.

References between resources are expressed as plain foreign-key fields holding another resource's `id` (for example, an order line's `order_id`, or a production slot's `committed_order_line_id`); these references are not polymorphic and carry no type prefix.

### 2.5. The Logical Clock and Scheduled Operations

All temporal behavior in the system — membership periods, quote expiry, source book release eligibility, delivery dispatch, and return windows — is evaluated against a server-maintained **logical clock**, never against the host wall clock. At server startup the logical clock is set to exactly `2026-09-01T00:00:00Z` and never falls back to wall-clock time.

A `PlatformAdmin` may advance the logical clock through an admin-only test-driving capability that sets it to a supplied `to_iso8601` instant. A second admin-only capability, the **daily ops run**, executes the scheduled work of the system in one checkpoint with a pinned, five-step ordering:

1. Auto-renew every `ACTIVE` member whose period has ended and whose `auto_renew` flag is set (charging the annual fee and rolling the period forward).
2. Move every remaining `ACTIVE` member whose period has ended — those without auto-renew — into `GRACE`, setting their grace window.
3. Move every `GRACE` member whose grace window has passed into `LAPSED`, firing the lapse cascade described in §3.1.
4. Release every source book edition that has completed its print lead time, firing the release cascade described in §3.3.
5. Dispatch every scheduled delivery appointment whose delivery date has been reached, moving it to `OUT_FOR_DELIVERY`.

The ordering matters: an implementation that dispatches appointments before releasing source books, or lapses members before attempting renewals, will produce observably different state. Every comparison against the clock uses the exact boundary rules stated where the rule is defined (for example, release requires the clock to be at or after the release-eligible instant, while lapse requires the clock to be strictly after the grace end).

### 2.6. Money, Units, and Rounding

All monetary values are integer cents. No endpoint accepts or returns fractional cents, and no monetary field is ever represented as a decimal number of dollars.

Rounding is pinned to a single method and a single application point: **round half up to integer cents, applied at the per-unit step before any multiplication or aggregation**. For every priced line, the discounted unit price is rounded half up to whole cents first, and only then multiplied by quantity. Per-line results are summed without further rounding. The same per-unit-then-aggregate discipline applies to restocking fees: the fee is computed and rounded per returned line, then summed. (For contrast: two lines each charged 1003 cents carry a restocking fee of 150 + 150 = 300 cents under the pinned rule; computing fifteen percent of the 2006-cent sum and rounding once would incorrectly yield 301 cents.) Sum-then-round is a rejected alternative everywhere in this system.

Route capacity is measured in whole minutes. Slot durations are computed as the difference between two clock instants, in whole minutes.

### 2.7. Pricing Tracks and the Pricing Tier Snapshot

Every order is priced under exactly one of three tracks, recorded on the order as `pricing_tier` with values `TRADE`, `MEMBER`, or `RETAIL`:

- An order created with a `trade_account_id` is a **trade order** and is priced `TRADE` regardless of anything else.
- An order created with a `member_id` whose member's computed standing is `MEMBER` at price time — that is, the member's `status` is `ACTIVE` or `GRACE` — is priced `MEMBER`.
- Every other order (a retail guest order with neither customer reference, or a member order whose member has dropped to `LAPSED` or a cancelled state) is priced `RETAIL`.

A member's own `pricing_tier` field is computed the same way: `MEMBER` while `status` is `ACTIVE` or `GRACE`, `RETAIL` otherwise. The per-line discount rates, promotional interaction, delivery fee schedule, and custom deposit terms that follow from each track are specified in §3.4.

Two snapshot rules keep pricing honest across time. First, each order line freezes `unit_list_price_cents` — the product's `list_price_cents` at line creation, with the premium-fabric uplift already applied where relevant — so later catalog price changes do not retroactively alter open orders. Second, an order in `QUOTE` keeps a `quote_total_cents` snapshot that is frozen at the moment the first line is added and never rewritten; the live `total_cents` keeps tracking current membership standing and the current promotional set, and the two may legitimately diverge (for example, when a source book releases between quoting and confirming).

### 2.8. Optimistic Concurrency Control on Confirmed Orders

Amendments to a confirmed order are protected by optimistic concurrency control. Both line-mutation operations on a `CONFIRMED` order — adding a line and removing a line — require the request to carry `expected_order_version`, a non-optional input field encoding the client's last-observed `version` of the order. If the supplied value does not match the order's current `version` — meaning another amendment has landed since the client last read the order — the mutation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is applied. While the order is still in `QUOTE`, the `expected_order_version` field is optional and, when present, ignored.

No other endpoint in the system takes a version field; OCC applies only to these two line-mutation operations.

### 2.9. Nested Resource Retrieval

Requests targeting nested resources validate path identifiers left to right. The first identifier in the path that does not resolve to an existing resource determines the error: a line operation against a non-existent order fails with `ERR_ORDER_NOT_FOUND` before the line id is examined at all, and a schedule-production request against a valid order but a non-existent line fails with `ERR_LINE_NOT_FOUND` before the slot is examined. The specialized not-found errors — `ERR_MEMBER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_GALLERY_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, and `ERR_TRADE_ACCOUNT_NOT_FOUND` — are used wherever the corresponding resource type is the one that failed to resolve; `ERR_NOT_FOUND` covers any remaining generic case. All not-found errors carry HTTP 404.

### 2.10. Validation Ordering

When several validation rules could reject the same request, the server evaluates them in a fixed priority order so the caller always sees the same error:

1. **Authentication** — presence and validity of the `X-User-Role` and `X-User-ID` headers (`ERR_UNAUTHENTICATED`).
2. **Authorization and ownership** — role allowed on the endpoint, and entity-backed identity matching (`ERR_FORBIDDEN`).
3. **Existence** — path resources resolved left to right (`ERR_NOT_FOUND` and the specialized 404 variants).
4. **State preconditions** — the transition's required from-state and standing checks (`ERR_INVALID_STATE` and its specialized forms `ERR_MEMBERSHIP_NOT_ACTIVE`, `ERR_TRADE_NOT_VERIFIED`, `ERR_LINE_NON_CANCELABLE`, `ERR_SLOT_NOT_OPEN`, `ERR_CUSTOM_LINE_NOT_DEPOSIT_PAID`; the empty-order confirm check `ERR_ORDER_EMPTY` also belongs to this tier).
5. **Referential business rules** — the referenced product exists and is orderable, fabric options match the product kind, and customer-reference exclusivity on order creation (`ERR_PRODUCT_UNAVAILABLE`, `ERR_PRODUCT_KIND_MISMATCH`).
6. **Temporal business rules** — quote expiry, slot overlap, daily route capacity, and the return window (`ERR_QUOTE_EXPIRED`, `ERR_SLOT_OVERLAP`, `ERR_ROUTE_CAPACITY_EXCEEDED`, `ERR_RETURN_WINDOW_CLOSED`).
7. **Constraint business rules** — uniqueness of emails and SKUs, the single-active-appointment rule, the stock-only return rule, and malformed input (`ERR_DUPLICATE_EMAIL`, `ERR_APPOINTMENT_EXISTS`, `ERR_CUSTOM_NON_RETURNABLE`, `ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM`).
8. **Fiscal business rules** — deposit presence and exact-amount checks at confirm (`ERR_DEPOSIT_REQUIRED`, `ERR_DEPOSIT_AMOUNT_MISMATCH`).

A request failing multiple tiers reports the error from the earliest tier only.

## 3. Business Logic & Workflows

### 3.1. The Membership Lifecycle: Enrollment, Renewal, Grace, Lapse, and Cancellation

An `Anonymous` caller enrolls a new member by supplying an `email`, a `full_name`, an `auto_renew` preference, and a `payment_token` (assumed valid; no payment gateway is modeled). The email must be unique across all members — a duplicate is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). Enrollment charges the annual membership fee of 17500 cents, records it in `fee_paid_total_cents`, stamps `current_period_start` with the current logical clock time, and sets `current_period_end` to exactly 365 days later. The new member enters in `ACTIVE` status.

A membership period is always exactly 365 days. When the logical clock moves strictly past a member's `current_period_end`, the next daily ops run resolves the period boundary: if `auto_renew` is set, the system charges another 17500 cents (adding to `fee_paid_total_cents`), slides `current_period_start` forward to the old `current_period_end`, extends `current_period_end` another 365 days from that new start, and the member stays `ACTIVE`; if `auto_renew` is not set, the member moves from `ACTIVE` to `GRACE` and `grace_end` is set to 30 days after the period end. `grace_end` is only ever populated while the member is in `GRACE`; it is null in every other status.

While in `GRACE`, a member retains full member pricing — their computed `pricing_tier` is still `MEMBER` — and may return to good standing through renewal, performed by the member themselves (or a `PlatformAdmin` acting on their behalf; when the caller has the `Member` role, `X-User-ID` must equal the member's `id`). Renewal from `GRACE` requires `status` to be exactly `GRACE` and supplies a fresh `payment_token`; it charges 17500 cents, restarts the period at the current clock time rather than at the old boundary (`current_period_start` becomes the clock, `current_period_end` becomes 365 days later), clears `grace_end` to null, and returns the member to `ACTIVE`. A renewal attempt against a member not in `GRACE` is rejected as an invalid state.

If the clock moves strictly past `grace_end` without a renewal, the daily ops run moves the member from `GRACE` to `LAPSED`, and the lapse fires a three-hop cascade. First (Cascade A hop 2), every design consultation belonging to this member that is still `SCHEDULED` is cancelled. Second (hop 3), each consultation cancelled in that step has its extension contribution removed from the order it was attached to: if that order is still in `QUOTE`, its `quote_expires_at` is recomputed as the order's `created_at` plus 14 days plus 14 days for each of the order's remaining `COMPLETED` consultations, and `consultation_extensions_used` is recomputed to match. Third (hop 2b), every order belonging to this member that is still in `QUOTE` is re-priced under the `RETAIL` track — per-line pricing and the order total are recomputed with retail rates, while the frozen `quote_total_cents` snapshot is left unchanged.

A member may also cancel at any time, but only the member themselves (a `Member` caller whose `X-User-ID` equals the member's `id`); this is the one membership action `PlatformAdmin` may not perform. Cancellation from `ACTIVE` splits on the refund window: if the clock is at or before 30 days after `current_period_start` — the window is inclusive of day 30 — the current period's fee of 17500 cents is refunded, `fee_paid_total_cents` is reduced by 17500, and the member ends in `CANCELLED_REFUNDED`; if the clock is past that point, no refund is given and the member ends in `CANCELLED`. Cancellation from `GRACE` is always without refund and ends in `CANCELLED`. All three of `CANCELLED`, `CANCELLED_REFUNDED`, and `LAPSED` are terminal.

Every fee event — enrollment, renewal, and refunded cancellation — recomputes the member's `lifetime_net_savings_cents`, which is always exactly `lifetime_gross_savings_cents` minus `fee_paid_total_cents`. Gross savings themselves accumulate only when member orders are delivered, as described in §3.7, never earlier.

### 3.2. The Trade Program: Application and Credential Verification

A design firm joins the trade program by applying with an `email`, a `business_name`, a `credential_document_id` referencing its credential evidence, and a `license_number`. The email must be unique across all trade accounts; duplicates are rejected with `ERR_DUPLICATE_EMAIL`. A new application enters in `APPLIED` status with no `tier` and no `decided_at`.

A `TradeReviewer` then renders a credential decision by supplying a `decision` of exactly `APPROVE` or `REJECT`. Approval additionally requires a `tier` of `TIER_1` or `TIER_2` — `TIER_1` carries a 30 percent trade discount and `TIER_2` a 40 percent discount — and transitions the account `APPLIED → VERIFIED`, recording the supplied tier and stamping `decided_at` with the clock. Rejection requires no tier and transitions `APPLIED → REJECTED`, also stamping `decided_at`; `REJECTED` is terminal. Any `decision` value outside the declared pair, or any `tier` outside `{TIER_1, TIER_2}`, is rejected with `ERR_INVALID_ENUM` (HTTP 400).

Only `VERIFIED` accounts may place or confirm trade orders: creating a trade order with an unverified account, or confirming one whose account has not reached `VERIFIED`, is rejected with `ERR_TRADE_NOT_VERIFIED` (HTTP 409). Once verified, the account's designer acts through the `TradeDesigner` role with `X-User-ID` equal to the trade account's `id`.

### 3.3. The Catalog and the Source Book Channel

A `PlatformAdmin` maintains the catalog and the gallery network. Each gallery is created with a `name`, a `region` code, and its `daily_route_minutes_capacity` — the white-glove route budget per calendar date, in minutes, that §3.7 enforces. Each product is created with a unique `sku` — a duplicate SKU is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409), the shared uniqueness-violation code — along with a `name`, a `list_price_cents` per unit, and a `line_kind` of `STOCK` or `CUSTOM` — the latter covering custom upholstery and special-order pieces. A product's `status` defaults to `ACTIVE` but may be created directly as `DISCONTINUED`; only `ACTIVE` products may be added to orders. Products also carry a computed `promo_active` flag, false at creation, which becomes true while a released source book promotes the product.

Source books are the marketing channel. A `PlatformAdmin` creates an edition with a `title`, a list of `product_ids` it promotes, and a `print_ready_date` recording when the files went to print. The edition enters immediately in `IN_PRINT`. Print production has a fixed lead time: an edition becomes eligible for release only once the logical clock is at or after 21 days past its `print_ready_date`, and release itself happens during the daily ops run — there is no manual release action.

Release fires Cascade B. The releasing edition moves `IN_PRINT → RELEASED` and stamps `released_at` with the clock. Because only one edition is ever current, any other edition in `RELEASED` moves to `ARCHIVED` at the same moment (Cascade B's archival hop): every product in the archived edition that is not also in the newly released edition has its `promo_active` set back to false. Then (hop 2) every product listed in the newly released edition's `product_ids` has `promo_active` set to true. Finally (hop 3), every order still in `QUOTE` that contains a product whose `promo_active` flag just changed — in either direction — is re-priced end to end: per-line pricing and the order total are recomputed against the new promotional set, with `quote_total_cents` again left frozen. `ARCHIVED` is terminal.

### 3.4. Orders, Quote Semantics, and the Pricing Engine

An order begins life as a quote. Order creation names the selling gallery via `gallery_id` and declares its customer reference: exactly one of `member_id` or `trade_account_id` may be supplied, or neither — supplying both is a malformed request and rejected with `ERR_INVALID_REQUEST` (HTTP 400). Three creation shapes follow. A member order is created by the `Member` themselves, with `member_id` equal to the caller's `X-User-ID`. A trade order is created by a `TradeDesigner` with `trade_account_id` equal to the caller's `X-User-ID`, and the account must already be `VERIFIED` or creation fails with `ERR_TRADE_NOT_VERIFIED`. A retail guest order carries neither reference and is created by a `GalleryAssociate` on the customer's behalf. The referenced trade account must exist; an unknown `trade_account_id` is rejected with `ERR_TRADE_ACCOUNT_NOT_FOUND`.

The new order enters in `QUOTE` with `quote_expires_at` set to 14 days after its creation time and `consultation_extensions_used` at zero. Its `pricing_tier` is resolved per §2.7, and all of its computed money fields — `quote_total_cents`, `subtotal_cents`, `white_glove_fee_cents`, `total_cents`, `deposit_due_cents`, `deposit_paid_cents`, `cancel_refund_cents` — start at zero, with `confirmed_at` and `delivered_at` null.

**Adding lines.** A line names a `product_id` and a `qty` of at least 1, and may carry a `fabric_tier` of `STANDARD` or `PREMIUM` (defaulting to `STANDARD`). The premium fabric option is meaningful only for custom upholstery: specifying `PREMIUM` on a `STOCK` product — or otherwise mismatching the fabric option to the product kind — is rejected with `ERR_PRODUCT_KIND_MISMATCH` (HTTP 422), and referencing a `DISCONTINUED` product is rejected with `ERR_PRODUCT_UNAVAILABLE` (HTTP 422). Referencing a product that does not exist yields `ERR_PRODUCT_NOT_FOUND`. At creation the line snapshots `unit_list_price_cents`: the product's current `list_price_cents`, multiplied by 1.25 when the line is a `CUSTOM` line with `fabric_tier` `PREMIUM`. A newly created `CUSTOM` line starts with `production_status` `PENDING_DEPOSIT`; a `STOCK` line's `production_status` is and remains `NONE`.

**The pricing engine.** Every line mutation — adding or removing a line — re-prices the whole order, as does confirm, member lapse, and source book release. The engine evaluates each line in a pinned order:

1. Take the line's frozen `unit_list_price_cents` as the base.
2. Compute the promotional price: if the product's `promo_active` is currently true, the base reduced by ten percent, rounded half up to integer cents; otherwise the base itself.
3. Apply the track. For a `TRADE` order the promotional price is ignored entirely — the unit price is the base reduced by the account's trade discount (thirty percent for `TIER_1`, forty percent for `TIER_2`), rounded half up to integer cents. For a `MEMBER` order the unit price is the promotional price reduced by twenty-five percent, rounded half up to integer cents. For a `RETAIL` order the unit price is the promotional price unchanged.
4. `line_charged_cents` is that rounded unit price multiplied by `qty`.

The order's `subtotal_cents` is the sum of `line_charged_cents` across its current lines — per-line rounding happens first, then the sum. The white-glove delivery fee then resolves against that subtotal: a `TRADE` order always pays a fee of 14900 cents with no waiver; a `MEMBER` or `RETAIL` order pays 19900 cents, waived to zero when the subtotal reaches 1000000 cents ($10,000.00) or more. An order in `QUOTE` with no lines carries a fee of zero. `total_cents` is `subtotal_cents` plus `white_glove_fee_cents`. The very first time a line is added to a quote, the resulting total is also captured into `quote_total_cents`, which thereafter never changes; this capture happens exactly once per order, so if every line is later removed and a new line is then added, the existing snapshot is kept and not re-captured.

**Custom deposits.** Each `CUSTOM` line additionally carries a non-cancelable `deposit_cents`, recomputed whenever the order is re-priced: the line's `line_charged_cents` multiplied by the deposit rate — one-half for member and retail orders, one-quarter for trade orders — rounded half up to integer cents, then raised to a floor of 50000 cents ($500.00) for member and retail orders or 25000 cents ($250.00) for trade orders when the computed amount falls below it. `STOCK` lines always have a deposit of zero. The order's `deposit_due_cents` is the sum of `deposit_cents` over its custom lines.

**Confirm.** Confirming a quote is the final settlement. The checks fire in §2.10 order: the order must be in `QUOTE` (otherwise `ERR_INVALID_STATE`, HTTP 409); it must contain at least one line (otherwise `ERR_ORDER_EMPTY`, HTTP 422); the clock must be at or before `quote_expires_at` (otherwise `ERR_QUOTE_EXPIRED`, HTTP 422); a member order's member must be in `ACTIVE` or `GRACE` standing (otherwise `ERR_MEMBERSHIP_NOT_ACTIVE`, HTTP 409); a trade order's account must be `VERIFIED` (otherwise `ERR_TRADE_NOT_VERIFIED`). If `deposit_due_cents` is greater than zero, the request must include `deposit_payment_cents` (its absence is rejected with `ERR_DEPOSIT_REQUIRED`, HTTP 422) and the supplied amount must equal `deposit_due_cents` exactly (a mismatch is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`, HTTP 422). On success the pricing engine is re-run end to end with the member standing and promotional set as of confirm time — the final settlement variant, in which `total_cents` may diverge from the frozen `quote_total_cents` — `deposit_paid_cents` is set to `deposit_due_cents`, every custom line moves from `PENDING_DEPOSIT` to `DEPOSIT_PAID`, and `confirmed_at` is stamped with the clock. An order with at least one custom line lands in `CONFIRMED`; an order with no custom lines at all skips that state and lands directly in `READY_FOR_DELIVERY`, since nothing stands between it and delivery scheduling.

**Amendment after confirm.** Lines may still be added to or removed from a `CONFIRMED` order, subject to the OCC rule of §2.8: the request must carry `expected_order_version` matching the order's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412). Quote-expiry does not gate confirmed-order amendments. Removal of a custom line is restricted by production progress: a custom line whose `production_status` is `IN_PRODUCTION` or `COMPLETE` can never be removed — the attempt is rejected with `ERR_LINE_NON_CANCELABLE` (HTTP 409). Removing a custom line in `DEPOSIT_PAID` or `COMMITTED` forfeits its deposit; if the line held a committed production slot, that slot returns from `COMMITTED` to `OPEN` (its `committed_order_line_id` is cleared and the gallery's reserved production minutes drop by the slot's duration), and the line's `production_status` becomes `RELEASED`. Every successful amendment re-runs the pricing engine, recomputes `deposit_due_cents`, refreshes the order's `updated_at`, and increments the order's `version` by exactly 1 — which is precisely what arms the OCC check for the next writer.

**Cancellation.** Cancelling from `QUOTE` is always permitted, charges nothing, and refunds nothing. Cancelling from `CONFIRMED` refunds the stock content only: `cancel_refund_cents` is set to the sum of `line_charged_cents` over the order's `STOCK` lines, while every custom deposit is forfeited, and each custom line holding a committed production slot releases that slot back from `COMMITTED` to `OPEN`. `DELIVERED` and `CANCELLED` are terminal; an order in either state cannot be cancelled, amended, or confirmed.

### 3.5. Custom Production: Workroom Slots and Scheduling

Custom upholstery and special-order pieces are produced against **production slots** opened on a gallery's workroom by a `ProductionPlanner`. A slot is defined by its `gallery_id`, a `starts_at`, and an `ends_at` that must be strictly later than `starts_at`; together they describe a half-open interval — the start instant belongs to the slot, the end instant does not. A new slot enters in `OPEN` status. Slot creation rejects overlap against any non-`CONSUMED` slot on the same gallery: two intervals conflict when the new slot's start is strictly before the existing slot's end **and** the existing slot's start is strictly before the new slot's end, in which case creation is rejected with `ERR_SLOT_OVERLAP` (HTTP 409). Pure adjacency — the new slot starting exactly when the existing one ends — does not conflict. Slots on different galleries never interact. The gallery tracks the production load imposed by its slots as `reserved_production_minutes`: the sum, in whole minutes, of each slot's duration (end minus start) over all of its slots in `COMMITTED` or `IN_PROGRESS`.

Committing a slot to a custom line is the scheduler's central act. The target line must be a `CUSTOM` line whose `production_status` is exactly `DEPOSIT_PAID` — a line in any other state, including `PENDING_DEPOSIT`, is rejected with `ERR_CUSTOM_LINE_NOT_DEPOSIT_PAID` (HTTP 409) — and the request supplies the `production_slot_id`. The named slot must be `OPEN` (otherwise `ERR_SLOT_NOT_OPEN`, HTTP 409) and must belong to the same gallery as the order. On commit, the slot moves `OPEN → COMMITTED`, its `committed_order_line_id` is set to the line, the line's `production_slot_id` is set to the slot, the line's `production_status` moves to `COMMITTED`, and the gallery's `reserved_production_minutes` rises by the slot's duration.

Production then advances in two steps, each driven by the planner supplying a `to_state`. Advancing a `COMMITTED` slot with `to_state` `IN_PROGRESS` moves the slot to `IN_PROGRESS` and the committed line's `production_status` to `IN_PRODUCTION`; the slot's minutes remain reserved. Advancing an `IN_PROGRESS` slot with `to_state` `CONSUMED` moves the slot to `CONSUMED` — its terminal state — moves the line's `production_status` to `COMPLETE`, and releases the slot's minutes from `reserved_production_minutes`. Any other `to_state` value is rejected with `ERR_INVALID_ENUM`, and any advance attempted from the wrong current state is rejected with `ERR_INVALID_STATE`.

That completion also bubbles up: when the last outstanding custom line of a `CONFIRMED` order reaches `COMPLETE` — that is, when every custom line on the order is `COMPLETE` — the order itself moves from `CONFIRMED` to `READY_FOR_DELIVERY` without any client action.

Slots unwind in the other direction too. When a custom line in `COMMITTED` is removed by amendment or its order is cancelled, its slot returns from `COMMITTED` to `OPEN`, `committed_order_line_id` is cleared to null, and the reserved minutes fall by the slot's duration, as described in §3.4.

### 3.6. Complimentary Design Consultations

Design services are provided at no additional fee, and every consultation is attached to a purchase. Booking a consultation supplies a `member_id`, an `order_id`, and a `scheduled_at` time; the consultation enters in `SCHEDULED`. The booking rules are: the named member must be in `ACTIVE` or `GRACE` standing (otherwise `ERR_MEMBERSHIP_NOT_ACTIVE`), the attached order must be in `QUOTE` or `CONFIRMED` (otherwise `ERR_INVALID_STATE`), and when the caller is a `Member`, the caller's `X-User-ID` must equal the consultation's `member_id` and the member must own the order — a `GalleryAssociate` may book on any member's behalf without the ownership check.

Completion is recorded by a `GalleryAssociate`, who supplies the `design_plan_notes`; the consultation moves `SCHEDULED → COMPLETED`, stamps `completed_at` with the clock, and — if the attached order is still in `QUOTE` — extends the quote: `quote_expires_at` gains 14 days and `consultation_extensions_used` increments by 1. Completing a consultation attached to an order no longer in `QUOTE` records the notes and completion but moves no expiry.

Consultations are cancelled in exactly one way: as hop 2 of Cascade A when the owning member lapses (§3.1). A consultation so cancelled moves `SCHEDULED → CANCELLED`, and the attached order — if still in `QUOTE` — has its `quote_expires_at` and `consultation_extensions_used` recomputed from its remaining `COMPLETED` consultations, so the cancelled consultation's extension disappears. `COMPLETED` and `CANCELLED` are both terminal.

### 3.7. White-Glove Delivery from Owned Hubs

Delivery runs through gallery-owned hubs. Scheduling an appointment — done by a `GalleryAssociate` or a `HubOperator` — supplies the `order_id`, the dispatching hub's `gallery_id`, a `delivery_date` as an ISO calendar date in `YYYY-MM-DD` form, the planned on-site `duration_minutes` covering room placement and assembly, and two service flags: `room_placement` for room-of-choice placement and `assembly_required` for assembly. The order must be in `READY_FOR_DELIVERY` (otherwise `ERR_INVALID_STATE`), and the order must not already have an appointment in `SCHEDULED` or `OUT_FOR_DELIVERY` — one active appointment per order; a second is rejected with `ERR_APPOINTMENT_EXISTS` (HTTP 409).

Each gallery enforces a daily route budget. Every appointment consumes its `duration_minutes` plus a fixed 30-minute route buffer, and the gallery's `booked_route_minutes` maps each ISO date to the sum of those consumed minutes over its appointments on that date in `SCHEDULED` or `OUT_FOR_DELIVERY`. A new appointment is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 422) when the minutes already consumed on that date plus the new appointment's duration plus its 30-minute buffer would be strictly greater than the gallery's `daily_route_minutes_capacity` — landing exactly on the budget is allowed. A successfully scheduled appointment enters in `SCHEDULED` and its minutes are added to `booked_route_minutes` for its date. If the same order has a prior appointment in `FAILED`, that prior appointment automatically moves to `RESCHEDULED` — terminal — with its `replaced_by_id` pointing at the new appointment.

On the morning of the route, the daily ops run dispatches every `SCHEDULED` appointment whose `delivery_date` has been reached — the clock's calendar date at or past the appointment's date — moving it to `OUT_FOR_DELIVERY`.

Outcome recording belongs to the `HubOperator` and applies only from `OUT_FOR_DELIVERY` (recording from any other state is `ERR_INVALID_STATE`). The request names an `outcome` of `COMPLETED` or `FAILED`; any other value is `ERR_INVALID_ENUM`. A `COMPLETED` outcome captures whether packaging removal was performed into `packaging_removed` (the field is false until then) and releases the appointment's minutes — duration plus buffer — from the gallery's `booked_route_minutes` for that date. A `FAILED` outcome requires a `failure_reason` to be supplied and likewise releases the booked minutes. Both `COMPLETED` and `RESCHEDULED` are terminal; `FAILED` is not — it awaits replacement by a newly scheduled appointment, as above.

The first appointment of an order to reach `COMPLETED` delivers the order: the order moves from `READY_FOR_DELIVERY` to its terminal `DELIVERED` state and stamps `delivered_at` with the clock. For member orders this is also the moment savings are recognized — and only this moment, never at confirm: the member's `lifetime_gross_savings_cents` increases by the difference between the order's undiscounted content (the sum over its lines of `unit_list_price_cents` multiplied by `qty`) and the amount actually charged (the sum of `line_charged_cents`), and `lifetime_net_savings_cents` is recomputed as gross savings minus `fee_paid_total_cents`.

### 3.8. Returns and Restocking

Returns apply to delivered orders, and the policy differs sharply between stock and custom merchandise: only `STOCK` lines may be returned; custom items are non-returnable and their deposits forfeited. A return request names the `order_id` and the list of `order_line_ids` being returned, and enters in `REQUESTED`. The request is valid only when the order is `DELIVERED` (otherwise `ERR_INVALID_STATE`), when the clock is at or before 30 days after the order's `delivered_at` — later requests are rejected with `ERR_RETURN_WINDOW_CLOSED` (HTTP 422) — and when every named line is a `STOCK` line of that order (any custom line in the list is rejected with `ERR_CUSTOM_NON_RETURNABLE`, HTTP 422).

Settlement belongs to the `GalleryAssociate`, who supplies a `decision`. On `APPROVE`, the restocking fee is computed per returned line as fifteen percent of that line's `line_charged_cents`, rounded half up to integer cents per line, and `restocking_fee_cents` is the sum of those per-line fees; `refund_cents` is the sum of the returned lines' `line_charged_cents` minus `restocking_fee_cents`. The request moves `REQUESTED → SETTLED` and stamps `decided_at` with the clock. On `REJECT`, a `reason` must be supplied, `refund_cents` is zero, and the request moves `REQUESTED → REJECTED`, also stamping `decided_at`. Both `SETTLED` and `REJECTED` are terminal, and any `decision` outside the declared pair is `ERR_INVALID_ENUM`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, perform an action, or read data return `200 OK`. The complete request and response semantics for each endpoint — inputs, preconditions, side effects, and cascades — are defined by the narratives of §2 and §3; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/members` | Enroll a member: charges the 17500-cent annual fee, starts the period at the clock, status `ACTIVE` | Anonymous |
| GET | `/members/{id}` | Read a member (a `Member` may read only itself) | Member, GalleryAssociate, PlatformAdmin |
| POST | `/members/{id}/renew` | Renew from `GRACE`: charges 17500, new period starts at the clock, back to `ACTIVE` | Member, PlatformAdmin |
| POST | `/members/{id}/cancel` | Cancel membership: full fee refund within the day-30-inclusive window (`CANCELLED_REFUNDED`), else `CANCELLED` without refund | Member |
| POST | `/trade-accounts` | Apply for the trade program with credentials; status `APPLIED` | Anonymous |
| POST | `/trade-accounts/{id}/verify` | Credential decision: `APPROVE` requires `tier`; `REJECT` is terminal | TradeReviewer |
| POST | `/galleries` | Create a gallery with its white-glove route capacity | PlatformAdmin |
| GET | `/galleries/{id}` | Read a gallery including `booked_route_minutes` and `reserved_production_minutes` | PlatformAdmin, GalleryAssociate, HubOperator, ProductionPlanner |
| GET | `/galleries/{id}/production-slots` | List production slots hosted by this gallery | ProductionPlanner, PlatformAdmin |
| POST | `/products` | Create a product; status defaults to `ACTIVE`, may be created `DISCONTINUED` | PlatformAdmin |
| GET | `/products/{id}` | Read a product including `promo_active` | Anonymous, Member, TradeDesigner, GalleryAssociate, PlatformAdmin, ProductionPlanner |
| GET | `/products/{id}/order-lines` | List order lines referencing this product | ProductionPlanner, PlatformAdmin, GalleryAssociate |
| POST | `/source-books` | Create a source book edition; enters `IN_PRINT`; released by the daily cycle at `print_ready_date` + 21 days | PlatformAdmin |
| POST | `/orders` | Create a `QUOTE` order: member order, trade order (account must be `VERIFIED`), or retail guest order | Member, TradeDesigner, GalleryAssociate |
| GET | `/orders/{id}` | Read an order (Member/TradeDesigner may read only their own orders) | Member, TradeDesigner, GalleryAssociate, HubOperator, PlatformAdmin, ProductionPlanner |
| GET | `/orders` | List orders with optional `member_id`, `trade_account_id`, `gallery_id`, `status` filters and envelope pagination | GalleryAssociate, PlatformAdmin |
| POST | `/orders/{id}/lines` | Add a line in `QUOTE` or `CONFIRMED` (confirmed requires `expected_order_version` OCC); re-prices the order | Member, TradeDesigner, GalleryAssociate |
| DELETE | `/orders/{id}/lines/{lineId}` | Remove a line in `QUOTE` or `CONFIRMED` (confirmed requires `expected_order_version` OCC); custom lines in production are non-cancelable | Member, TradeDesigner, GalleryAssociate |
| GET | `/orders/{id}/lines` | List lines of an order | Member, TradeDesigner, GalleryAssociate, ProductionPlanner, PlatformAdmin |
| POST | `/orders/{id}/lines/{lineId}/schedule-production` | Commit an `OPEN` production slot to a `DEPOSIT_PAID` custom line | ProductionPlanner |
| POST | `/orders/{id}/confirm` | Confirm a quote: final settlement re-price; exact deposit payment required when custom lines exist; zero-custom orders go straight to `READY_FOR_DELIVERY` | Member, TradeDesigner, GalleryAssociate |
| POST | `/orders/{id}/cancel` | Cancel from `QUOTE` (no refund) or `CONFIRMED` (stock lines refunded, custom deposits forfeited, committed slots released) | Member, TradeDesigner, GalleryAssociate |
| POST | `/production-slots` | Open a production slot on a gallery workroom; half-open overlap check against non-`CONSUMED` slots of the same gallery | ProductionPlanner |
| GET | `/production-slots/{id}` | Read a production slot | ProductionPlanner, PlatformAdmin |
| POST | `/production-slots/{id}/advance` | Advance `COMMITTED → IN_PROGRESS` or `IN_PROGRESS → CONSUMED`; consumption completes the line and may bubble the order to `READY_FOR_DELIVERY` | ProductionPlanner |
| POST | `/design-consultations` | Book a free design consultation attached to a `QUOTE` or `CONFIRMED` purchase | Member, GalleryAssociate |
| GET | `/design-consultations/{id}` | Read a consultation | Member, GalleryAssociate, PlatformAdmin |
| GET | `/design-consultations` | List consultations with optional `member_id`, `order_id`, `status` filters and envelope pagination | GalleryAssociate, PlatformAdmin |
| POST | `/design-consultations/{id}/complete` | Complete a consultation; extends the attached `QUOTE`'s expiry by 14 days | GalleryAssociate |
| POST | `/delivery-appointments` | Schedule white-glove delivery: order must be `READY_FOR_DELIVERY`, no active appointment for the order, gallery daily route capacity enforced (duration + 30-minute buffer) | GalleryAssociate, HubOperator |
| GET | `/delivery-appointments/{id}` | Read an appointment | GalleryAssociate, HubOperator, Member, PlatformAdmin |
| GET | `/delivery-appointments` | List appointments with optional `gallery_id`, `order_id`, `delivery_date` filters and envelope pagination | GalleryAssociate, HubOperator, PlatformAdmin |
| POST | `/delivery-appointments/{id}/record-outcome` | Record `COMPLETED` (packaging removal captured) or `FAILED` (reason required); both release the booked route minutes; first completion delivers the order | HubOperator |
| POST | `/returns` | Request return of `STOCK` lines of a `DELIVERED` order within 30 days of `delivered_at` | Member, TradeDesigner, GalleryAssociate |
| GET | `/returns/{id}` | Read a return request | Member, TradeDesigner, GalleryAssociate, PlatformAdmin |
| GET | `/returns` | List return requests with optional `order_id`, `status` filters and envelope pagination | GalleryAssociate, PlatformAdmin |
| POST | `/returns/{id}/settle` | Settle: `APPROVE` computes the per-line-rounded restocking fee and refund; `REJECT` requires a reason and refunds zero | GalleryAssociate |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving); startup default is exactly 2026-09-01T00:00:00Z and never falls back to wall-clock | PlatformAdmin |
| POST | `/_ops/run_daily_cycle` | Ops-run checkpoint (test-driving): (1) auto-renew, (2) `ACTIVE → GRACE`, (3) `GRACE → LAPSED` with Cascade A, (4) source book release with Cascade B, (5) dispatch due appointments | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an index of identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_GALLERY_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONSULTATION_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_TRADE_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 Conflict |
| `ERR_TRADE_NOT_VERIFIED` | 409 Conflict |
| `ERR_ORDER_EMPTY` | 422 Unprocessable Entity |
| `ERR_LINE_NON_CANCELABLE` | 409 Conflict |
| `ERR_SLOT_NOT_OPEN` | 409 Conflict |
| `ERR_CUSTOM_LINE_NOT_DEPOSIT_PAID` | 409 Conflict |
| `ERR_PRODUCT_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_PRODUCT_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_QUOTE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RETURN_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_APPOINTMENT_EXISTS` | 409 Conflict |
| `ERR_CUSTOM_NON_RETURNABLE` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
