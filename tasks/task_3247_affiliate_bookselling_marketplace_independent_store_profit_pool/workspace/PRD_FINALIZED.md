# Affiliate Bookselling Marketplace API — Product Requirements Document

## 1. Introduction

Independent bookstores have long been shut out of online bookselling: they lack the logistics to ship direct-to-consumer, and the platforms that do ship books keep the entire margin. This document specifies the Affiliate Bookselling Marketplace API, the backend for a marketplace in which independent bookstore storefronts earn a commission on sales made through their links, while a separate monthly profit pool redistributes a share of platform profit to participating stores that generate little or no direct sales of their own.

The marketplace inverts the usual fulfillment topology. Orders are placed by customers against an affiliate-attributed link, but every parcel ships from a wholesale distributor — the affiliate store never touches inventory. Author, publication, and influencer affiliates participate alongside storefronts under their own commission bands. Customer service is handled centrally by a platform service desk, even though the customer-facing relationship continues to feel local to the shopper's home store. Publisher and wholesaler terms — wholesale discount percentages, return windows, and return credit rates — flow directly into per-order economics, while ebook and audiobook titles follow a separate revenue mechanic in which the platform retains a partner-share before commission is computed.

Because commissions, pool distributions, and payouts all settle through a single commission ledger, the financial core of the system is reconciliation: every ledger mutation immediately re-derives the affected affiliate's accrued balance, and a payout release sweep converts balances above a threshold into payable instruments. This document is the sole normative specification for those rules; implementers should treat the prose in §2 and §3 as the contract and §4 and §5 as the structural index.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity in which they act. A request whose `X-User-Role` header is missing or does not name one of the declared roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the endpoint — or, on lifecycle action endpoints, not mapped to the specific `action` being attempted — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly seven roles: `PlatformAdmin`, `StoreManager`, `Partner`, `Customer`, `CustomerService`, `WholesalerOps`, and `FinanceOps`.

The `PlatformAdmin` role is the marketplace operator. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. A `PlatformAdmin` onboards stores and partners, manages the publisher and book catalog, schedules promotions, drives every store and partner lifecycle action, and controls the logical clock.

The `StoreManager` role operates one independent bookstore storefront. When `X-User-Role` is `StoreManager`, `X-User-ID` is the `id` of the acting `AffiliateStore`; ownership checks on any resource that references an `AffiliateStore` — most notably a list's `owner_store_id` — compare the resource's foreign-key field to `X-User-ID`. A mismatch is rejected with `ERR_FORBIDDEN_OWNER_MISMATCH` (HTTP 403).

The `Partner` role is an author, publication, or influencer affiliate. When `X-User-Role` is `Partner`, `X-User-ID` is the `id` of the acting `AffiliatePartner`, and ownership checks compare resource fields such as `affiliate_partner_id` against it. Partners have no exclusive write operations; they read their own record, ledger entries, and payouts, and browse books and lists to build curation links.

The `Customer` role is the buyer. No `Customer` entity is persisted: the customer relationship is carried entirely by the opaque `customer_id` handle stored on each order. When `X-User-Role` is `Customer`, `X-User-ID` is an opaque customer handle, and on any endpoint acting on an order, a return of an order, or a ticket of an order, the server requires `X-User-ID` to equal the order's `customer_id`; a mismatch yields `ERR_FORBIDDEN_OWNER_MISMATCH`.

The `CustomerService` role is the central service desk. When `X-User-Role` is `CustomerService`, `X-User-ID` is an opaque operator identifier not compared to any entity's `id`. The desk approves and rejects returns, assigns, resolves and closes tickets, and may cancel a customer's order on the customer's behalf.

The `WholesalerOps` role operates the distributor side. When `X-User-Role` is `WholesalerOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. `WholesalerOps` dispatches orders to the wholesaler, emits ship and deliver fulfillment events, and logs physical receipt of returned stock.

The `FinanceOps` role runs money movement. When `X-User-Role` is `FinanceOps`, `X-User-ID` is an opaque operator identifier not compared to any entity's `id`. `FinanceOps` owns the profit pool lifecycle, the payout lifecycle, and the crediting of returns.

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

Endpoints that return collections accept two query parameters. The `limit` parameter bounds the page size: it defaults to 10 when omitted, and values below 1 or above 100 are outside the accepted range. The `offset` parameter skips a number of leading records and defaults to 0. Unless a more specific rule is stated, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

All time-dependent behavior in the marketplace — promotion activation windows, publisher return windows, pool period boundaries, ticket reopen windows, and store pool-eligibility day counts — is evaluated against a single server-held logical clock, never against wall-clock time. At server startup the logical clock is exactly `2026-09-01T00:00:00Z`; the server must never fall back to wall-clock time at any point. A `PlatformAdmin` test-driving capability advances the clock to a supplied `to_iso8601` instant. Advancing the clock re-evaluates every promotion's lifecycle transitions against the new time, as described in §3.3.

### 2.5. Common Resource Properties

Every top-level resource carries a system-managed `id`, formatted as a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Resources with full lifecycle bookkeeping additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that increments by one on every mutation to the resource. Creation is itself the first mutation, so a newly created resource starts at `version` 1, and the first subsequent mutation advances it to 2. Lifecycle actions that mutate a store, an order, a distribution, or any other versioned resource therefore advance its `version` even when the only visible change is a state field. The commission ledger is the deliberate exception: a `CommissionLedgerEntry` carries only `id` and `created_at` — it has no `updated_at` and no `version`, because ledger entries are immutable once written (supersession is expressed through the `reversed` flag, not through in-place edits).

### 2.6. Money, Precision, and Rounding

All monetary quantities are integer cents — there are no fractional-cent amounts anywhere in the system. Every calculation that divides or applies a percentage rounds per line (or per store, in the case of pool shares) using a floor toward zero before any summation: round each component down to a whole cent first, then sum the rounded components. This per-component-floor rule applies identically to order line pricing, commission accrual, return credits, wholesale credits, commission clawbacks, and pool share allocation, and it is what makes a summation over independently rounded components reproducible by any reader. Percentage fields such as `discount_pct`, `commission_pct`, `ebook_partner_rev_share_pct`, and `return_credit_pct` are fractions (a value of 0.46 means 46%), each bounded by the band given where the field is introduced.

### 2.7. The Commission Ledger and Balance Reconciliation

The marketplace keeps a single append-only commission ledger. Every economic event that changes what an affiliate is owed is expressed as a `CommissionLedgerEntry` carrying a signed `amount_cents` and a `kind` drawn from `ORDER_ACCRUAL`, `COMMISSION_REVERSAL`, `RETURN_CLAWBACK`, `POOL_DISTRIBUTION`, or `ADJUSTMENT`. Accruals and pool distributions are positive; reversals and clawbacks are negative. Each entry names exactly one beneficiary through `affiliate_store_id` or `affiliate_partner_id`, and an origin `order_id` for order-derived kinds; pool entries instead carry `pool_distribution_id`, and `ADJUSTMENT` entries may carry neither reference.

An affiliate's `accrued_balance_cents` is a derived figure, never written directly: it is the sum of the `amount_cents` of that affiliate's ledger entries whose `reversed` flag is false, minus the `amount_cents` of the affiliate's payouts that have reached `PAID`. The server reconciles this balance on every ledger mutation, so readers always observe a current value. Once an entry has been superseded — by final settlement or by an explicit reversal — its `reversed` flag becomes true and it drops out of the balance computation permanently.

Closely tied to reconciliation is the payout release sweep. After any event that raises an affiliate's `accrued_balance_cents` — an order accrual at placement or delivery, or a pool distribution — the server checks that one affiliate: if the balance is greater than or equal to the affiliate's `payout_threshold_cents`, and no payout for that affiliate currently sits in `PENDING` or `PROCESSING`, and the affiliate's own status is `ACTIVE`, a new payout is opened for exactly the current balance as a frozen snapshot. A balance exactly equal to the threshold does release. Balances below the threshold simply accrue until a later event lifts them across.

### 2.8. Attribution and the Store-Local Customer Relationship

Every sale is attributable to exactly one affiliate: either an independent store or an author/publication/influencer partner, never both and never neither. Orders carrying both `attributed_store_id` and `attributed_partner_id`, or neither, are rejected with `ERR_ATTRIBUTION_AMBIGUOUS` (HTTP 422). Attribution is distinct from the customer's sense of place: an order may also carry a `home_store_id` identifying the store the relationship feels local to. Service and notifications remain branded to that home store even though fulfillment is wholesale and the service desk is central — the home store is presentation, not obligation.

### 2.9. Nested Resource Retrieval

Endpoints whose paths contain more than one resource identifier validate those identifiers strictly left to right. The first path identifier that does not resolve to an existing resource produces an `ERR_NOT_FOUND` (HTTP 404) response, and no later segment is examined. Foreign keys arriving in a request body — publisher references on books, attribution and home-store references on orders, the owner store on a list, book identifiers inside list items and order lines — are validated separately and surface as `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

### 2.10. Optimistic Concurrency Control on Pool Approval

Exactly one write operation in the API is guarded by optimistic concurrency control: approving a profit pool distribution. That request must carry `expected_distribution_version`, the distribution `version` the client last observed. Because every calculate, recalculate, approve, and distribute advances the distribution's `version`, a client acting on an earlier view holds a stale number; if the supplied value does not match the distribution's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.11. Validation Ordering

When a request could fail several rules at once, the server evaluates checks in a fixed order and reports the first failure. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then ownership (`ERR_FORBIDDEN_OWNER_MISMATCH`). Path resources are resolved next (`ERR_NOT_FOUND`), followed by body foreign keys (`ERR_REFERENCE_NOT_FOUND`), then body shape — required fields, types, enum membership, uniqueness, list positions, and index ranges — as `ERR_VALIDATION` (HTTP 400). Only then are state-machine preconditions checked (`ERR_INVALID_STATE`, HTTP 409), followed by the pool-approval OCC check (`ERR_STALE_VERSION`). Business safety rules come after state: affiliate-active checks (`ERR_AFFILIATE_NOT_ACTIVE`, HTTP 422) and book availability (`ERR_BOOK_UNAVAILABLE`, HTTP 422). Business constraint checks follow — attribution exclusivity, list-attribution consistency, promotion window conflicts, and pool period overlap — then temporal windows (`ERR_RETURN_WINDOW_CLOSED`, `ERR_WINDOW_NOT_SATISFIED`), then fiscal rules (`ERR_COMMERCIAL_TERMS_INVALID`, `ERR_POOL_SUM_MISMATCH`), and finally referential guards (`ERR_STORE_SETTLEMENT_OUTSTANDING`, `ERR_LIST_NOT_PUBLISHABLE`, `ERR_RETURN_QUANTITY_EXCEEDED`).

## 3. Business Logic & Workflows

### 3.1. The Catalog: Publishers, Wholesale Terms, and Books

Before anything can be sold, a `PlatformAdmin` registers the publishers whose terms govern print economics. A publisher record carries a display `name`, a wholesale `discount_pct` — the fraction of list price the wholesaler grants, anywhere from 0.00 to 0.60 inclusive, so a value of 0.46 means books from this publisher cost the platform 54% of list — and the publisher's returns policy: `returns_allowed` (whether print returns to the wholesaler are permitted at all), `return_window_days` (how many days after delivery a return may still be opened, where 0 means no returns even when `returns_allowed` is true), and `return_credit_pct` (the fraction of a line's wholesale cost the publisher credits back on a credited return, from 0.00 to 1.00 inclusive). A publisher registered with terms outside these bands is rejected with `ERR_COMMERCIAL_TERMS_INVALID` (HTTP 422). Each publisher is born `ACTIVE`; a publisher whose terms fall into dispute becomes `SUSPENDED`, and books of a suspended publisher cannot be placed on new orders.

Books enter the catalog under a publisher via a payload carrying `publisher_id`, an `isbn` unique across the entire catalog, a display `title`, a `format` of `PRINT`, `EBOOK`, or `AUDIOBOOK`, and a `list_price_cents` that must be greater than zero. Digital titles additionally carry `ebook_partner_rev_share_pct` — the platform's share of net revenue taken before affiliate commission, between 0.00 and 0.50 inclusive — and this field is required for `EBOOK` and `AUDIOBOOK` formats and must be null or absent for `PRINT`. Every book is born `LISTED`; a `DELISTED` book can no longer be ordered or added to lists. The catalog is browsable in both directions: a publisher's books are reachable through the publisher, which is how consumers of `Book.publisher_id` reverse-navigate the relationship.

### 3.2. Affiliate Onboarding: Stores and Partners

An independent bookstore joins the marketplace when a `PlatformAdmin` onboards it with a `shop_name`, a `slug` that must be unique after lowercase normalization, a `commission_pct` between 0.10 and 0.30 inclusive, an optional `pool_opt_in` flag defaulting to true that governs participation in the monthly profit pool, and an optional `payout_threshold_cents` defaulting to 2500 and never accepted below that floor. Terms outside these bands are rejected with `ERR_COMMERCIAL_TERMS_INVALID`. A new store starts in `PENDING_ONBOARDING` with `accrued_balance_cents` at zero, and transitions to `ACTIVE` only when a `PlatformAdmin` activates it — an action that stamps `activated_at` with the logical clock, clears `suspended_at`, and advances the store's `version`. The `activated_at` timestamp matters well beyond ceremony: pool-eligibility day counts measure from the most recent entry into `ACTIVE`.

Suspension and reactivation form a cycle around that anchor. The store status dimension runs `PENDING_ONBOARDING` → `ACTIVE` → `SUSPENDED` → `ACTIVE` → `DEACTIVATED`. Suspending an `ACTIVE` store stamps `suspended_at`, advances `version`, and — critically — blocks new order attribution to the store from that moment (enforced at placement). Reactivating a `SUSPENDED` store stamps a fresh `activated_at`, opening a new eligibility epoch for pool day counts, clears `suspended_at`, and advances `version` again. Deactivation is the terminal act, permitted from either `ACTIVE` or `SUSPENDED`, but only when the store's `accrued_balance_cents` is exactly zero and no payout for the store sits in `PENDING` or `PROCESSING`; otherwise the request fails with `ERR_STORE_SETTLEMENT_OUTSTANDING` (HTTP 422). A `DEACTIVATED` store is excluded from all future pool distributions.

Author, publication, and influencer affiliates follow a parallel but distinct track. An application records a `display_name`, a `partner_kind` of `AUTHOR`, `PUBLICATION`, or `INFLUENCER`, a `commission_pct` between 0.05 and 0.15 inclusive — a deliberately narrower band than stores — and an optional `payout_threshold_cents` defaulting to 1000 with that value as its floor. Applications begin in `APPLIED`. A `PlatformAdmin` may approve an application, moving the partner to `APPROVED` — a state in which the partner exists but may not yet be attributed on orders — and only a subsequent activation moves the partner to `ACTIVE`, where order attribution becomes possible. An application may instead be rejected outright from `APPLIED`, moving it to `REJECTED`, which is terminal. Suspending an `ACTIVE` partner blocks new order attribution and additionally freezes the partner's money in place: pending payouts for the partner cannot move into processing until reactivation. A suspended partner is reactivated by the same activation action used after approval.

### 3.3. Curation and Demand: Lists and Promotions

Lists are the discovery engine. A `StoreManager` creates a list by supplying `owner_store_id` — which must be the manager's own store — a `title`, and an inline `items` array whose entries pair a `book_id` with a 1-based `position` unique within the list and an optional `curator_note`. Every referenced book must exist and be `LISTED`; the array may be empty at creation. Lists are born in `DRAFT`. Publishing requires a non-empty list (an empty publish attempt fails with `ERR_LIST_NOT_PUBLISHABLE`, HTTP 422) and an owning store whose status is `ACTIVE`; publishing increments the list's `publish_count` and makes the list eligible to drive order attribution. A published list can be unpublished back to `DRAFT` — it then attributes no new orders, though existing orders keep their recorded `source_list_id` — and re-publishing from `DRAFT` counts as another publish. Archiving is terminal and reachable from either `DRAFT` or `PUBLISHED`; an `ARCHIVED` list preserves its items read-only.

Promotions are scheduled per title. A `PlatformAdmin` schedules a promotion by naming a `book_isbn` — which must resolve to an existing `LISTED` book at creation time — together with a customer-facing `discount_pct` between 0.05 and 0.40 inclusive (outside the band, `ERR_COMMERCIAL_TERMS_INVALID`), and a closed-interval window from `window_start` through `window_end`, where the end must not precede the start. Windows on the same ISBN must not merely avoid overlapping; they must leave at least a full day's buffer between one another. Concretely, a new window conflicts with an existing non-`ENDED` promotion on the same ISBN unless the new start falls strictly more than one day after the existing window's end, or the new end falls strictly more than one day before the existing window's start; violations are rejected with `ERR_PROMOTION_WINDOW_CONFLICT` (HTTP 409). Promotions that have already `ENDED` no longer block anything.

Promotion lifecycle is clock-driven, not action-driven. A promotion begins `SCHEDULED`; when the logical clock reaches a moment inside its closed window it becomes `ACTIVE` and starts participating in line pricing; when the clock passes `window_end` it becomes `ENDED`. A clock jump that carries the current instant past `window_end` while the promotion is still `SCHEDULED` moves it directly to `ENDED` without an `ACTIVE` interlude. These transitions are re-evaluated on every clock advance and on every read of the promotion.

### 3.4. Orders: Placement, Pricing, and Wholesale Fulfillment

A `Customer` composes an order in `DRAFT` by supplying their own `customer_id` handle, at least one line in the `lines` array — each line pairing a `book_id` with a `quantity` of at least one — and the attribution fields: exactly one of `attributed_store_id` or `attributed_partner_id` per §2.8. The order may optionally record a `home_store_id` for branding and a `source_list_id` naming the list that drove discovery. A source list, when present, must be `PUBLISHED`, must be owned by the attributed store, and implies store attribution — a `source_list_id` on a partner-attributed order is contradictory and rejected with `ERR_LIST_ATTRIBUTION_MISMATCH` (HTTP 422), as is a list that is unpublished or owned by a different store.

Placement is where the order becomes economic fact. Placing requires the order in `DRAFT` with `payment_status` still `PENDING` and at least one line; the attributed affiliate — store or partner — must be `ACTIVE`, or the placement is rejected with `ERR_AFFILIATE_NOT_ACTIVE` (HTTP 422); and every line's book must be `LISTED` with a publisher that is `ACTIVE`, failing which the placement is rejected with `ERR_BOOK_UNAVAILABLE` (HTTP 422). A successful placement moves the order to `PLACED` and, in the same request, flips `payment_status` from `PENDING` to `PAID` — payment capture is atomic with placement.

Pricing happens at this moment and is then pinned. Each line, processed in payload order, is priced from the book's `list_price_cents`: if a promotion matches the book's ISBN, is `ACTIVE`, and the placement instant falls inside its closed window, the unit price is the list price minus the list price multiplied by the promotion's `discount_pct` floored to a whole cent; otherwise the unit price is the list price. The line total is that unit price multiplied by quantity. The wholesale unit cost depends on format: for `PRINT` it is the list price multiplied by one minus the publisher's `discount_pct` snapshot at placement, floored; for `EBOOK` and `AUDIOBOOK` it is the list price multiplied by a flat digital cost basis of 30%, floored. The order's `gross_cents` is the sum of the per-line totals — summed strictly after each line's own rounding, in pinned payload order — and `wholesale_cost_cents` is the sum of each line's floored wholesale unit cost multiplied by its quantity. All of these per-line snapshots — `unit_price_cents`, `line_total_cents`, `wholesale_unit_cents`, and a `returned_quantity` starting at zero — are written into the order's computed `priced_lines` array, indexed from 0 in payload order.

Commission accrues immediately, but provisionally. Per priced line, by format: for `PRINT`, the line's net is its `line_total_cents` minus its `wholesale_unit_cents` times quantity, and the line commission is that net multiplied by the affiliate's `commission_pct`, floored. For digital formats, the platform first keeps its partner share — the `line_total_cents` multiplied by the book's `ebook_partner_rev_share_pct`, floored — and the line commission is what remains after that platform keep, multiplied by the affiliate's `commission_pct`, floored. The order's `commission_cents` is the sum of these per-line floors; its `platform_margin_cents` is, for print lines, each line's total minus its wholesale cost minus its commission, and for digital lines, each line's total minus the platform keep minus its commission, all summed. This provisional figure is written to the ledger as an `ORDER_ACCRUAL` entry with `reversed` false, the affiliate's `accrued_balance_cents` is reconciled, and the payout release sweep runs for that affiliate.

After placement, the wholesaler owns the parcel. Dispatching a `PLACED` and `PAID` order hands it to the distributor (`SENT_TO_WHOLESALER`); the affiliate store never touches inventory. Shipping advances the order to `SHIPPED`, and delivery to `DELIVERED`, stamping `delivered_at` with the logical clock — the instant from which all return windows are measured. Delivery also finalizes the commission: the provisional `ORDER_ACCRUAL` entry is marked `reversed` true, a fresh final `ORDER_ACCRUAL` entry recomputed by the same per-line formula supersedes it, the affiliate's balance is reconciled again, and the payout sweep runs once more. Identical inputs can therefore yield different ledger state when a reversal has landed between placement and delivery.

Cancellation has two shapes. An order's fulfillment lifecycle runs `DRAFT` → `PLACED` → `SENT_TO_WHOLESALER` → `SHIPPED` → `DELIVERED`, with `CANCELLED` as the terminal alternative reachable from `DRAFT` or `PLACED`; its payment lifecycle is the parallel dimension `PENDING` → `PAID` → `REFUNDED_PARTIAL` → `REFUNDED_FULL`, independent of fulfillment. Cancelling while the order is still in `DRAFT` is a quiet act — no commission entry was ever written, so nothing needs clawing back. Cancelling a `PLACED` order — available to the owning customer or to `CustomerService` acting on their behalf — requires the order paid, and unwinds the money: `payment_status` becomes `REFUNDED_FULL`, `refunded_cents` is set to the full `gross_cents` and `retained_cents` to zero, the provisional accrual entry is marked reversed, and a `COMMISSION_REVERSAL` ledger entry for the negative amount is written against the affiliate. On cancellation from `PLACED` this reversal entry is itself written already superseded — its `reversed` flag is `true` from birth — so that under the balance rule of §2.7 both the reversed original accrual and the reversal entry drop out of the balance computation and the affiliate's balance returns to its pre-placement value; the affiliate's balance is then reconciled. Throughout the order's life, `retained_cents` always equals `gross_cents` minus `refunded_cents` and is recomputed on every return credit. Orders are listable and filterable by customer, by either attribution field, by `source_list_id`, by `home_store_id`, and by `fulfillment_status`, which is how consumers of the order's foreign keys reverse-navigate them.

### 3.5. After the Sale: Returns and Service Tickets

Returns are opened against a delivered order's priced lines. A return request names the order (from the path), a `line_index` — the 0-based position into the order's `priced_lines` — a `quantity`, and a `reason_code` of `DAMAGED`, `WRONG_ITEM`, or `UNWANTED`. Opening a return against an order that has not reached `DELIVERED` fails with `ERR_INVALID_STATE` (HTTP 409). The quantity must be at least one and must not exceed the line's quantity minus the units already returned on that line; excess is rejected with `ERR_RETURN_QUANTITY_EXCEEDED` (HTTP 422). Two temporal and format rules guard creation itself: for `PRINT` lines, the publisher's `returns_allowed` must hold and the logical clock must be no later than `delivered_at` plus the publisher's `return_window_days`; for `EBOOK` and `AUDIOBOOK` lines, the `UNWANTED` reason is rejected outright — digital goods are never returnable simply because the customer changed their mind. Either violation surfaces as `ERR_RETURN_WINDOW_CLOSED` (HTTP 422).

A `CustomerService` operator then decides the request. A return's lifecycle runs `REQUESTED` → `APPROVED` → `RECEIVED` → `CREDITED`, with `REJECTED` as the terminal alternative out of `REQUESTED`. Approval — the `REQUESTED` → `APPROVED` transition — requires the order delivered and re-checks the same print-window and digital-reason rules as creation, because time may have advanced between the two; approval also fixes the customer refund, setting `refund_cents` to the line's `unit_price_cents` multiplied by the return `quantity`. Rejection is terminal. For print, `WholesalerOps` logs physical receipt, moving the request to `RECEIVED`; digital formats take the same step in the same call, there being nothing physical to wait for.

Crediting is a `FinanceOps` act and the point where the money moves. Crediting increments the priced line's `returned_quantity` by the returned quantity, adds `refund_cents` to the order's `refunded_cents`, and recomputes `retained_cents`; the order's `payment_status` becomes `REFUNDED_PARTIAL`, or `REFUNDED_FULL` when the cumulative refund equals the full `gross_cents`. The wholesaler side is settled through `wholesale_credit_cents`: for a `PRINT` line whose publisher allows returns, it is the line's `wholesale_unit_cents` times the returned quantity times the publisher's `return_credit_pct`, floored; for digital formats it is always zero, and the platform absorbs the full refund. The affiliate's commission is clawed back proportionally: a `RETURN_CLAWBACK` ledger entry is written for the negative of the line's final per-line commission multiplied by the fraction of the line being returned — returned quantity over line quantity — floored, and the affiliate's `accrued_balance_cents` is reconciled.

Service tickets run in parallel to returns and cover the whole order, not a line. A customer opens a ticket with an `order_id`, an `opened_by_customer_id` that must equal the order's `customer_id` (and, for the `Customer` role, the caller's `X-User-ID`), and an `issue_kind` of `LATE_SHIPMENT`, `DAMAGED_ITEM`, `WRONG_ITEM`, or `BILLING`. Tickets begin `OPEN` and follow the lifecycle `OPEN` → `IN_REVIEW` → `RESOLVED` → `REOPENED` → `IN_REVIEW` → `RESOLVED` → `CLOSED`, with `CLOSED` reachable from `OPEN` or `RESOLVED` as the terminal state; `CustomerService` assigns them into `IN_REVIEW` and resolves them from there, which stamps `resolved_at` with the logical clock and notifies the customer under the order's home-store branding — a presentation detail only, carrying no state. Resolution is not necessarily the end: the customer may reopen a `RESOLVED` ticket within fourteen days of `resolved_at` measured against the logical clock, and a reopen attempted after that window fails with `ERR_WINDOW_NOT_SATISFIED` (HTTP 422); a reopened ticket returns to `IN_REVIEW` through a fresh assignment. Closure is reachable from `OPEN` directly or from `RESOLVED`, and is terminal. Throughout, the desk may attach a `resolution_note` — the central team's words, surfaced to the customer under their local store's brand.

### 3.6. The Monthly Profit Pool

The profit pool is how stores that generate no direct sales still share in the marketplace. A `FinanceOps` operator opens a distribution in `DRAFT` — the distribution lifecycle runs `DRAFT` → `CALCULATED` → `APPROVED` → `DISTRIBUTED`, with recalculate returning `CALCULATED` to `DRAFT` and `VOID` as the terminal alternative out of `DRAFT` — with a `period_start` (inclusive), a `period_end` (exclusive, and required to fall after the start), the `pool_cents` committed to the pool — which must be greater than zero, else `ERR_COMMERCIAL_TERMS_INVALID` — and a `share_mode` of `EQUAL_SPLIT` or `SALES_WEIGHTED`. Periods are half-open intervals, and a new period must not intersect any existing non-`VOID` distribution's period under that half-open test; back-to-back periods, where one ends exactly as the next begins, are allowed. Overlaps are rejected with `ERR_POOL_PERIOD_OVERLAP` (HTTP 409).

Calculation turns the `DRAFT` distribution into `CALCULATED`, and only once the period has fully elapsed — `period_end` must be at or before the logical clock, failing which the request is rejected with `ERR_WINDOW_NOT_SATISFIED`. Calculation first applies the eligibility gate: for every store with `pool_opt_in` true that is not `DEACTIVATED`, the server counts the whole calendar days within the period on which the store held `ACTIVE` status for the entire day, derived from its `activated_at` and `suspended_at` epochs — a store suspended mid-period forfeits the days from suspension until reactivation. A store is eligible when it was active for at least 14 such days; a store active exactly 14 days is eligible. The count of eligible stores becomes `eligible_store_count`.

Shares are then allocated per the mode. Under `EQUAL_SPLIT`, each eligible store receives `pool_cents` divided by `eligible_store_count`, floored — a store with zero direct sales earns exactly what the top seller earns. Under `SALES_WEIGHTED`, each eligible store's weight is the sum of `gross_cents` over orders attributed to it that reached `DELIVERED` with `delivered_at` inside the period, and its share is `pool_cents` multiplied by its weight over the total weight, floored; if no eligible store has any delivered sales in the period, the allocation falls back to the equal-split arithmetic. Either way, the floored shares rarely sum exactly to the pool: the unallocated `remainder_cents` — the pool minus the sum of floored shares — is credited to exactly one store, the eligible store with the earliest `created_at` under equal split, or the eligible store with the largest weight (ties broken by earliest `created_at`) under sales weighting. Ineligible stores still appear in `share_lines`, marked `eligible` false with `share_cents` zero. If no store is eligible at all, every share is zero, the remainder is zero, and the pool stays unallocated — which the approval sum-check will refuse to lock. Calculation populates the full `share_lines` array (each line carrying `store_id`, `eligible`, and `share_cents`), and advances the distribution's `version`. A recalculate returns the distribution from `CALCULATED` to `DRAFT`, emptying `share_lines` and resetting `eligible_store_count` and `remainder_cents` to zero, and likewise advances `version`.

Approval locks the shares. It requires the distribution in `CALCULATED`, the OCC check of §2.10, and the sum invariant: the `share_cents` across `share_lines` must total exactly `pool_cents`, else `ERR_POOL_SUM_MISMATCH` (HTTP 422). Because the pool's `version` advances on every calculate, recalculate, approve, and distribute, an approval carrying a version captured before the latest calculation is stale — the approver's view of the share lines no longer matches what would be locked — and is rejected with `ERR_STALE_VERSION` per §2.10. Distribution itself moves each eligible share line with a positive amount — processed in order of store `created_at` ascending — into a `POOL_DISTRIBUTION` ledger entry naming the distribution via `pool_distribution_id`; each write reconciles that store's `accrued_balance_cents`, and after the final write the payout release sweep runs, opening payouts for every affiliate whose balance now meets its threshold. A distribution may instead be voided from `DRAFT`, which is terminal.

### 3.7. Payouts: Releasing the Money

Payouts are never created by hand; they exist only because the release sweep of §2.7 opened one, carrying an `amount_cents` frozen as the affiliate's accrued balance at that instant. A payout begins `PENDING`; its lifecycle runs `PENDING` → `PROCESSING` → `PAID`, with a `PROCESSING` → `FAILED` → `PENDING` retry cycle, and `PAID` as the only terminal state. `FinanceOps` moves it to `PROCESSING` — but only while the beneficiary affiliate, store or partner, is itself `ACTIVE`; processing against a suspended affiliate is rejected with `ERR_AFFILIATE_NOT_ACTIVE`. Marking the payout paid is terminal and debits the affiliate: the payout's `amount_cents` is subtracted from the affiliate's `accrued_balance_cents` as the ledger-derived balance is reconciled. A processing payout may instead fail, recording a `failure_reason`; failure is not terminal — a retry returns the payout to `PENDING` and clears the `failure_reason`, ready to begin the cycle again. Payouts are listable and filterable by `affiliate_store_id`, `affiliate_partner_id`, and `status`, and the ledger itself is browsable by affiliate, by `order_id`, by `pool_distribution_id`, and by `kind`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all lifecycle action endpoints, return `200 OK`. The single clock-control endpoint returns `200 OK` and no resource body. Request and response shapes for each endpoint are defined by the narratives of §2 and §3; the table below is the structural index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/bookshop/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/bookshop/publishers` | Register a publisher with wholesale terms | PlatformAdmin |
| GET | `/bookshop/publishers/{id}` | Fetch a publisher | PlatformAdmin, WholesalerOps, FinanceOps |
| GET | `/bookshop/publishers/{id}/books` | List a publisher's books | PlatformAdmin, WholesalerOps, StoreManager, Partner, Customer |
| POST | `/bookshop/books` | Add a catalog title | PlatformAdmin |
| POST | `/bookshop/stores` | Onboard an independent bookstore storefront | PlatformAdmin |
| GET | `/bookshop/stores/{id}` | Fetch a store including its accrued balance | PlatformAdmin, StoreManager, FinanceOps, CustomerService |
| GET | `/bookshop/stores/{id}/lists` | List a store's curated lists | PlatformAdmin, StoreManager, Partner, Customer |
| POST | `/bookshop/stores/{id}/actions` | Store lifecycle: activate, suspend, reactivate, deactivate | PlatformAdmin |
| POST | `/bookshop/partners` | Submit an author/publication/influencer affiliate application | PlatformAdmin |
| GET | `/bookshop/partners/{id}` | Fetch a partner including its accrued balance | PlatformAdmin, Partner, FinanceOps |
| POST | `/bookshop/partners/{id}/actions` | Partner lifecycle: approve, reject, activate, suspend | PlatformAdmin |
| POST | `/bookshop/lists` | Create a store-curated list with inline items | StoreManager |
| POST | `/bookshop/lists/{id}/actions` | List lifecycle: publish, unpublish, archive | StoreManager (owning) |
| POST | `/bookshop/orders` | Create an order in DRAFT with attribution and inline lines | Customer |
| GET | `/bookshop/orders/{id}` | Fetch an order including totals and priced lines | Customer, CustomerService, PlatformAdmin, FinanceOps, WholesalerOps |
| GET | `/bookshop/orders` | List and filter orders | Customer, CustomerService, PlatformAdmin, FinanceOps, WholesalerOps |
| POST | `/bookshop/orders/{id}/actions` | Order lifecycle: place, cancel, dispatch, ship, deliver | Customer (place, cancel), CustomerService (cancel), WholesalerOps (dispatch, ship, deliver) |
| POST | `/bookshop/orders/{id}/returns` | Open a return against a priced line of a delivered order | Customer, CustomerService |
| GET | `/bookshop/orders/{id}/returns` | List an order's returns | Customer, CustomerService, PlatformAdmin, WholesalerOps, FinanceOps |
| GET | `/bookshop/orders/{id}/tickets` | List an order's service tickets | Customer, CustomerService, PlatformAdmin |
| POST | `/bookshop/returns/{id}/actions` | Return lifecycle: approve, reject, receive, credit | CustomerService (approve, reject), WholesalerOps (receive), FinanceOps (credit) |
| GET | `/bookshop/ledger-entries/{id}` | Fetch a commission ledger entry | PlatformAdmin, StoreManager, Partner, FinanceOps |
| GET | `/bookshop/ledger-entries` | List and filter commission ledger entries | PlatformAdmin, StoreManager, Partner, FinanceOps |
| POST | `/bookshop/pool-distributions` | Open a profit pool distribution in DRAFT | FinanceOps |
| POST | `/bookshop/pool-distributions/{id}/actions` | Pool lifecycle: calculate, recalculate, approve, distribute, void | FinanceOps |
| GET | `/bookshop/payouts/{id}` | Fetch a payout | FinanceOps, PlatformAdmin, StoreManager, Partner |
| GET | `/bookshop/payouts` | List and filter payouts | FinanceOps, PlatformAdmin, StoreManager, Partner |
| POST | `/bookshop/payouts/{id}/actions` | Payout lifecycle: process, mark-paid, fail, retry | FinanceOps |
| POST | `/bookshop/tickets` | Open a central service ticket on an order | Customer |
| POST | `/bookshop/tickets/{id}/actions` | Ticket lifecycle: assign, resolve, reopen, close | CustomerService (assign, resolve, close), Customer (reopen) |
| POST | `/bookshop/promotions` | Schedule a per-ISBN discount window | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNER_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_AFFILIATE_NOT_ACTIVE` | 422 |
| `ERR_BOOK_UNAVAILABLE` | 422 |
| `ERR_ATTRIBUTION_AMBIGUOUS` | 422 |
| `ERR_LIST_ATTRIBUTION_MISMATCH` | 422 |
| `ERR_PROMOTION_WINDOW_CONFLICT` | 409 |
| `ERR_POOL_PERIOD_OVERLAP` | 409 |
| `ERR_RETURN_WINDOW_CLOSED` | 422 |
| `ERR_WINDOW_NOT_SATISFIED` | 422 |
| `ERR_COMMERCIAL_TERMS_INVALID` | 422 |
| `ERR_POOL_SUM_MISMATCH` | 422 |
| `ERR_LIST_NOT_PUBLISHABLE` | 422 |
| `ERR_RETURN_QUANTITY_EXCEEDED` | 422 |
| `ERR_STORE_SETTLEMENT_OUTSTANDING` | 422 |
