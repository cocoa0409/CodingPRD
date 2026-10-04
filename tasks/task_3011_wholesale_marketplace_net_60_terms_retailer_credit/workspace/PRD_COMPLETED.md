# Wholesale Marketplace Credit API - Product Requirements Document

## 1. Introduction

Independent retail lives and dies on cash flow. A boutique that discovers a promising candle brand at market cannot afford to pay for inventory upfront and wait sixty days for the sell-through to recover the outlay; likewise, a small brand shipping its first wholesale order to an unknown retailer has no practical way to underwrite that buyer's creditworthiness. The Wholesale Marketplace Credit API closes that gap by acting as the trusted middleman: retailers are verified against proof of an active storefront and a valid resale certificate, brands onboard with explicit commercial terms, and the marketplace itself extends net-60 credit to qualifying retailers while paying brands on a fixed schedule regardless of whether the retailer's invoice has been collected.

This document specifies the API surface and business rules for that platform. It covers the retailer verification pipeline (including its resubmission loop), brand onboarding and the configuration each brand must declare before it may sell, credit line assignment and the underwriting model that adjusts limits as payment behavior accumulates, order placement with territory-exclusivity and credit gating, net-60 invoicing with payment allocation and write-off handling, the return-authorization flow with its free-opening-order policy and abuse guard, commission-tiered brand payouts decoupled from retailer collection risk, and the fraud-screening cascade that protects the marketplace from straw storefronts, consumer resellers, and return-abusive brands.

All operations are evaluated against a single logical clock. The clock starts at exactly 2026-09-01T00:00:00Z on server startup and only advances when an administrative operator moves it; it never falls back to wall-clock time. Time-dependent behaviors such as invoice lateness, exclusivity expiry, lead-time eligibility, and payout scheduling are all expressed against this logical clock.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across every endpoint in the API. The entire API surface is mounted under `/wholesale` (with one administrative clock endpoint as the sole exception, documented in §4).

### 2.1. User and Role-Based Access Control

Every request to the API is identified by two HTTP headers: `X-User-ID` identifies the acting caller and `X-User-Role` declares the caller's capacity. The platform recognizes five roles with these exact spellings: `Anonymous`, `PlatformAdmin`, `RiskAnalyst`, `Retailer`, and `Brand`.

A request whose `X-User-Role` header is missing or does not name one of the declared roles, or whose `X-User-ID` header is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but is not in the set of roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Beyond role membership, entity-backed callers are subject to an ownership check: when an entity-backed role acts on a resource it owns, the resource's foreign key must match the caller's `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403).

The `Anonymous` role exists solely to support retailer self-registration; for `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. `PlatformAdmin` is the marketplace operator responsible for verification decisions, credit administration, returns receipt, payout operations, fraud adjudication, and clock control; `X-User-ID` for `PlatformAdmin` is likewise an opaque operator identifier not tied to any persisted entity, and the server never compares it to an entity `id`. `RiskAnalyst` is a risk-team member who raises fraud flags and reads credit and fraud posture; `X-User-ID` for `RiskAnalyst` is an opaque operator identifier not tied to any persisted entity.

When `X-User-Role` is `Retailer`, `X-User-ID` is the `id` of the acting `Retailer`; ownership checks on any resource that references a `Retailer` compare the resource's `retailer_id` field to `X-User-ID`. When `X-User-Role` is `Brand`, `X-User-ID` is the `id` of the acting `Brand`; ownership checks on any resource that references a `Brand` compare the resource's `brand_id` field to `X-User-ID`. This identity rule is what lets the platform distinguish, for example, a brand shipping its own order from one attempting to ship another brand's order.

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

Requests that hit no declared route (HTTP 404) or a declared route with the wrong method (HTTP 405) also return the standard error envelope, with `error_id` `ERR_INVALID_REQUEST`.

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it is clamped to a minimum of 1 and a maximum of 100 — an out-of-range value is clamped, not rejected, while a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `offset` parameter sets how many items to skip; it defaults to 0 and is clamped to a minimum of 0. Unless otherwise specified, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order, with creation sequence breaking ties when `created_at` values are equal. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` counts all matching resources (not just the returned page) and `has_more` is true exactly when more resources exist beyond the returned page. The batch payout-processing endpoint is also paginated: its response lists only the payouts this run actually moved to `PROCESSING`.

### 2.4. Common Resource Properties

Every primary resource in the platform — Retailer, Brand, CreditAccount, Order, OrderLine, Invoice, ReturnAuthorization, ReturnLine, Payout, ExclusivityGrant, and FraudFlag — carries a standard set of system-managed fields: an `id` that is a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp recording when the resource was created — rendered with three fractional digits when the logical clock carries a fractional second and without the fractional segment when it does not, matching the clock-rendering rule of §2.5; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and a `version` integer that starts at 1 at creation and increments by one on every mutation to the resource. Any mutation, including system-driven reconciliation, refreshes `updated_at` and bumps `version`.

The Payment resource is the single exception: because a payment record is an immutable ledger entry once recorded, it carries only `id` and `created_at`; it has neither `updated_at` nor `version`.

### 2.5. The Logical Clock and Lazy Time Evaluation

Time inside the platform is governed by a logical clock rather than the host wall clock. On server startup the logical clock is exactly 2026-09-01T00:00:00Z, and it advances only when a `PlatformAdmin` explicitly sets it by supplying a `to_iso8601` instant, after which the server reports the new logical time as `now_iso8601` (when the set instant carries zero fractional seconds the reported `now_iso8601` omits the milliseconds segment entirely, e.g. `2026-09-01T00:00:00Z`). An `to_iso8601` value that cannot be parsed as an ISO 8601 instant is rejected with `ERR_INVALID_REQUEST` (HTTP 400); a naive instant is interpreted as UTC, and a `Z` suffix or an explicit offset is accepted and normalized to UTC. The clock-set response is the success envelope whose `data` is `{"now_iso8601": ...}`. Nothing in the system reads wall-clock time; lead-time checks, invoice due dates, exclusivity windows, payout schedules, and write-off eligibility all compare against the logical clock.

Two time-driven transitions are evaluated lazily rather than by a background scheduler. An invoice that is still `OPEN` flips to `OVERDUE` when the logical clock has passed its `due_date` while a balance remains, but the flip is applied the next time a read or write touches that invoice. Likewise an exclusivity grant in `ACTIVE` whose `ends_at` has been reached flips to `EXPIRED` the next time the grant is read or an order placement is evaluated against it. In both cases the flip itself is a mutation and therefore refreshes the entity's `updated_at` and increments its `version`.

### 2.6. Nested Resource Retrieval

Endpoints that address nested resources validate path identifiers strictly left to right. A request that references an order and then one of its invoices, return authorizations, or lines first confirms that the order exists; only then does it resolve the nested identifier. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve, and the same left-to-right rule applies to identifiers referenced inside a request body. Existence checks precede every other validation category.

### 2.7. Money, Units, and Rounding

All monetary amounts in the system are integers denominated in cents — `limit_cents`, `available_cents`, `subtotal_cents`, `amount_cents`, `amount_due_cents`, `paid_amount_cents`, `balance_cents`, `gross_cents`, `commission_cents`, `net_cents`, `return_fee_cents`, `credit_cents`, and `payout_balance_cents` are all integer-cent values. Where a calculation produces a fractional cent (the commission calculation and the non-opening-order return fee), the result is rounded half-up to whole cents; the credit limit underwriting calculation needs no rounding because every term is already an integral number of cents.

The retailer's `return_rate` is the one non-monetary computed ratio in the system, and it is persisted to exactly four decimal places using round-half-up; it is represented in API responses as a JSON number equal to the rounded ratio. Distances for territory evaluation are computed in double precision, and the comparison against a grant's radius is strict.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. A credit limit review submitted for an account must carry `expected_credit_account_version`, the account `version` the reviewer last observed; if the account's current `version` has advanced — because a payment, shipment, return, or write-off has since mutated the account's derived fields — the review is rejected with `ERR_STALE_VERSION` (HTTP 412), so a reviewer never re-underwrites an account whose posture they have not seen. Correspondingly, whenever a payment, shipment, return receipt, or write-off mutates the account's derived fields (`available_cents` and, where applicable, the limit or tier the account reflects), that mutation advances the account's `version` and refreshes its `updated_at` like any other mutation, per §2.4. Likewise, creating an exclusivity grant must carry `expected_brand_version`, the brand `version` the client last observed; if the brand's `version` has advanced — through a new grant, a payout accrual, or an abuse assessment — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than these two do not accept a version field.

### 2.9. Cross-Entity Consistency and Cascades

The platform treats certain state changes as events that propagate. When a retailer is suspended as a result of fraud adjudication, the suspension is not isolated: the retailer's credit account freezes, every still-placed order of that retailer is cancelled, and each of those cancellations makes the affected brand whole through a compensating payout. Conversely, when an invoice is written off, the brand's already-accrued payout is deliberately left untouched — collection risk on net-60 terms belongs to the platform, not to the brand. Return receipt is similarly multi-entity: a single receive event adjusts the order's lines, the invoice, the order's fulfillment state, and the retailer's return-rate in one coherent step. These cascades are described alongside the workflows that trigger them in §3.

### 2.10. The Payout Ledger Principle

Each brand carries a running ledger, `payout_balance_cents`, that is the single source of truth for money the marketplace owes the brand. Shipping an order credits the ledger by the payout's net amount; processing a due payout debits the ledger by the same amount, and the debit is recorded even when it would drive the balance negative — the balance is permitted to go negative after abuse assessments. A failed transfer reverses its debit exactly, crediting the same net amount back so the next processing run can retry. Because the payout schedule is fixed at shipment time and never revisited, retailer payment behavior — late, partial, or never — has no effect on what the brand is owed or when.

## 3. Business Logic & Workflows

### 3.1. Retailer Onboarding and the Verification Loop

A prospective retail buyer joins the marketplace by self-registering as `Anonymous`, supplying the business's `legal_name`, its `store_type` (one of `BRICK_AND_MORTAR`, `ONLINE`, or `HYBRID`), the storefront `address` together with its geographic coordinates `lat` and `lng`, a `storefront_proof_url` pointing at evidence of an active storefront (a photo, a lease, or a live web shop), and a `resale_certificate_no` carrying the state resale certificate or seller's permit number. A `store_type` value outside the three accepted spellings is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Registration may optionally include a `referral_code`; when the supplied code matches a brand's referral code, the registration is permanently bound to that brand, and that binding later fixes the channel attribution of every order the retailer places with that brand. A code that matches no brand does not fail registration — the retailer is registered unbound, and its orders are attributed as `MARKETPLACE` per §3.4.

A freshly registered retailer lands in `PENDING` with both document sub-states — `storefront_proof_status` and `resale_cert_status` — also `PENDING`, a `verification_resubmission_count` of zero, a `return_rate` of zero, and a null `risk_tier` that remains null until a credit account assigns one per §3.3. From there a `PlatformAdmin` drives the review. Each document is adjudicated individually through a document-review action carrying a `document_type` and a `decision`, which sets the corresponding sub-state to `CONFIRMED` or `REJECTED` (each review bumps the retailer's `version` and refreshes `updated_at`). The accepted `document_type` spellings are `storefront_proof` (or `STOREFRONT_PROOF`) for the storefront-proof sub-state and `resale_certificate` (or `RESALE_CERTIFICATE`, `resale_cert`, or `RESALE_CERT`) for the resale-certificate sub-state. The accepted `decision` spellings are `CONFIRM` or `CONFIRMED` to confirm the document, and `REJECT` or `REJECTED` to reject it; any other value is rejected with `ERR_INVALID_REQUEST`. Only when the overall verification is requested with an approving `decision` — `APPROVE` (the spellings `approve` and `APPROVED` are also accepted; rejection takes `REJECT`, with `reject` and `REJECTED` also accepted; any other value is rejected with `ERR_INVALID_REQUEST`) — does the full check fire: the retailer must still be `PENDING` (any other verification status fails with `ERR_INVALID_STATE`, HTTP 409, regardless of whether the decision is an approval or a rejection), and both `storefront_proof_status` and `resale_cert_status` must be `CONFIRMED`; an approval attempted while either document is unconfirmed is rejected with `ERR_VERIFICATION_INCOMPLETE` (HTTP 422). A successful approval moves the retailer `PENDING → VERIFIED`, while a rejecting `decision` moves it `PENDING → REJECTED`.

An administrator who cannot yet decide may instead move the retailer `PENDING → MORE_INFO_REQUESTED` (optionally recording a `reason`); requesting more info from any other verification status fails with `ERR_INVALID_STATE` (HTTP 409). The retailer itself — and only that retailer, since `X-User-ID` must equal the retailer's own `id` — may then resubmit a fresh `storefront_proof_url` and `resale_certificate_no`, which returns the retailer to `PENDING`, resets both document sub-states to `PENDING`, and increments `verification_resubmission_count`. Resubmission is legal only from `MORE_INFO_REQUESTED`; a resubmission attempted from any other status is rejected with `ERR_INVALID_STATE` (HTTP 409) before the count is consulted. This loop is capped: a resubmission attempted when the count has already reached 3 is rejected with `ERR_RESUBMISSION_LIMIT` (HTTP 422), so a retailer cycles through at most three rounds of additional information.

Suspension arrives from the fraud path rather than from verification: confirming a storefront- or reseller-type fraud flag against a `VERIFIED` retailer moves it `VERIFIED → SUSPENDED`, with the cascade described in §3.7.

### 3.2. Brand Onboarding and Commercial Configuration

A brand joins by creating its own profile as the `Brand` role, declaring a display `name`, a `contact_email`, and four commercial parameters that govern every order it will ever accept: `min_order_value_cents`, the smallest order subtotal the brand will fulfill; `default_case_pack_size`, the packing multiple every order line quantity must respect; `lead_time_days`, the minimum days between order placement and earliest allowed shipment; and `payout_delay_days`, the fixed number of days after shipment when the brand's payout falls due, independent of when (or whether) the retailer pays. At creation the brand is in `DRAFT` and the server mints its `referral_code` — a `REF-`-prefixed alphanumeric string — the code the brand shares with retailers it recruits to the platform.

Activation is the brand's own act. A brand may move itself `DRAFT → ACTIVE` only while still in `DRAFT` (activation from any other status fails with `ERR_INVALID_STATE`, HTTP 409), only when acting as itself, and only when its configuration is complete: `min_order_value_cents` greater than zero, `default_case_pack_size` at least 1, `lead_time_days` at least 0, and `payout_delay_days` at least 1; an incomplete configuration is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A brand that has been suspended through the return-abuse mechanism described in §3.7 sits in `SUSPENDED` until a `PlatformAdmin` reinstates it, returning it to `ACTIVE` (reinstatement of a brand not in `SUSPENDED` fails with `ERR_INVALID_STATE`, HTTP 409); suspension is reversible precisely because remediation may follow. Attempting to ship while the brand is not `ACTIVE` fails with `ERR_BRAND_SUSPENDED` (HTTP 422), and an order placed against a brand that is not `ACTIVE` fails with `ERR_CASE_PACK_VIOLATION` (HTTP 422) as described in §3.4.

### 3.3. Credit Underwriting and the Retailer Credit Account

Once a retailer is `VERIFIED`, a `PlatformAdmin` opens its credit account by referencing the `retailer_id`. Each retailer has exactly one account: opening one for a retailer not in `VERIFIED`, or for a retailer that already has an account, is rejected with `ERR_INVALID_STATE` (HTTP 409). At opening, the underwriting calculation runs in its provisional form — the retailer has no invoice history yet, so the limit is purely a function of store type — and the account comes up `ACTIVE` with `available_cents` equal to the freshly computed `limit_cents`; opening the account also assigns the retailer's `risk_tier` from that provisional limit.

The credit ceiling is computed as follows. Every retailer starts from a base by store type: 250,000 cents for `BRICK_AND_MORTAR`, 150,000 cents for `ONLINE`, and 200,000 cents for `HYBRID`. The behavioral variant then considers the retailer's full invoice history — every invoice of every status belonging to this retailer's orders, examined in ascending order of invoice `created_at` with `due_date` ascending as the tie-break (orders cancelled before shipment never produce an invoice and so contribute nothing). An invoice counts toward the on-time tally when it reached `PAID` and the payment that drove its balance to zero was recorded with a `paid_at` no later than the invoice's `due_date`; an invoice counts toward the adverse tally when it is `WRITTEN_OFF`, or when it reached `PAID` but the settling payment's `paid_at` fell after the `due_date`. The limit equals the base, plus 50,000 cents for each on-time invoice, minus 100,000 cents for each adverse invoice, and the result is then clamped to lie between 50,000 cents on the low end and 1,000,000 cents on the high end inclusive. The retailer's `risk_tier` derives from the clamped limit: a limit of 100,000 cents or less is `HIGH`, a limit above 100,000 and at most 400,000 cents is `MEDIUM`, and anything above 400,000 cents is `LOW`.

A `PlatformAdmin` re-runs the underwriting at any time through a limit review on the account. The review is OCC-guarded per §2.8: the request must carry `expected_credit_account_version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful review recomputes `limit_cents` under the behavioral variant, resets `available_cents` to the new limit minus the sum of the retailer's outstanding invoice balances, recomputes the linked retailer's `risk_tier`, and increments the account's `version`.

Account status moves with the retailer's standing. When a retailer is suspended, its `ACTIVE` account automatically transitions `ACTIVE → FROZEN`. Once the retailer is `VERIFIED` again, an administrator may unfreeze the account, returning it `FROZEN → ACTIVE`; an unfreeze attempted on an account not in `FROZEN`, or whose linked retailer is not `VERIFIED`, is rejected with `ERR_INVALID_STATE` (HTTP 409). An account that will never be rehabilitated may instead be closed — but only from `FROZEN`, and only when no invoice belonging to any of this retailer's orders is currently `OVERDUE` (the lazy overdue evaluation of §2.5 is applied to those invoices first); violating either precondition is rejected with `ERR_INVALID_STATE` (HTTP 409). The `CLOSED` state is terminal.

### 3.4. Order Placement and Its Validation Ladder

A verified retailer places a wholesale order as the `Retailer` role, submitting a payload with its own `retailer_id`, the target `brand_id`, and a list of `lines`, each naming the brand's `sku`, the wholesale `unit_price_cents`, and a `qty`. Order placement runs the full validation ladder in a fixed order — the ordering matters because it determines which error a multi-defect request surfaces first. Authentication, role authorization, ownership, and entity existence come first (§2.1 and §2.6), followed by request-body shape, then the OCC check where applicable, then state-machine legality. Request-body shape validation is uniform across the API: the body must be a JSON object (a non-object body is rejected with `ERR_INVALID_REQUEST`, HTTP 400, while a missing or unparsable body is treated as an empty object); any field not declared for the endpoint is rejected with `ERR_INVALID_REQUEST`; a declared field that is missing or null when required, or whose value has the wrong type, is rejected with `ERR_INVALID_REQUEST`. For order placement specifically, `lines` must be a non-empty array of objects, each carrying exactly a string `sku`, a non-negative integer `unit_price_cents`, and an integer `qty`; any deviation is rejected with `ERR_INVALID_REQUEST`. After those generic gates, the business checks fire in this sequence: the fraud gate (`ERR_FRAUD_HOLD`), the case-pack and brand-active check (`ERR_CASE_PACK_VIOLATION`), the territory check (`ERR_TERRITORY_CONFLICT`), the minimum-order-value check (`ERR_MIN_ORDER_VALUE`), and finally the credit check (`ERR_CREDIT_LIMIT_EXCEEDED`).

The fraud gate requires that the acting retailer have no fraud flag still in `OPEN` status and that the retailer's `verification_status` be `VERIFIED`; a retailer under an open flag, or one whose verification is incomplete, rejected, or suspended, is turned away with `ERR_FRAUD_HOLD` (HTTP 422). The case-pack check requires the brand to be `ACTIVE` and every line's `qty` to be a positive multiple of the brand's `default_case_pack_size`. The minimum-order check requires the computed `subtotal_cents` to be at least the brand's `min_order_value_cents`. The credit check requires the retailer's credit account to be `ACTIVE` with `available_cents` at least equal to the `subtotal_cents`; a missing, frozen, or closed account, or insufficient headroom, yields `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422).

When an order is accepted, two attributes are fixed at placement and never change. The `attribution` is `BRAND_REFERRED` if the retailer's registration was bound to this brand's referral code, and `MARKETPLACE` otherwise. The `order_seq` is the 1-based position of this order within the retailer-brand pair, ordered by `created_at` ascending; `order_seq` equal to 1 marks the opening order, which matters for free returns (§3.6) and commission tiering (§3.5). Each line's `amount_cents` is the exact product of its `qty` and `unit_price_cents` — an integer of cents needing no rounding — and the order's `subtotal_cents` is the sum of those per-line amounts. Each line also tracks a `net_sold_qty`, initially equal to `qty`, which return receipts will later draw down. New orders begin in `PLACED`. (Shipment re-checks the retailer's standing and fails with `ERR_FRAUD_HOLD` when the purchasing retailer is no longer `VERIFIED`; see §3.5.)

Territory exclusivity is evaluated at placement time, per the rules in §3.8: if any currently-`ACTIVE` grant for this brand covers the retailer's storefront, the placement is rejected with `ERR_TERRITORY_CONFLICT` (HTTP 422).

A retailer may cancel its own order while it is still `PLACED`, moving it `PLACED → CANCELLED`; cancellation after shipment is not possible through the retailer path.

### 3.5. Shipment, Invoicing, and Payout Scheduling

Shipment is the brand's act and the financial heart of the platform. A brand ships one of its own orders — `X-User-ID` must equal the order's `brand_id` — moving it `PLACED → SHIPPED` (an order in any other status fails with `ERR_INVALID_STATE`, HTTP 409), but only when the brand is `ACTIVE`, the purchasing retailer is `VERIFIED`, and the logical clock has reached at least the order's `created_at` plus the brand's `lead_time_days`; shipping too early fails with `ERR_LEAD_TIME_NOT_MET` (HTTP 422), shipping while the brand is not active fails with `ERR_BRAND_SUSPENDED` (HTTP 422), and shipping when the purchasing retailer is no longer `VERIFIED` fails with `ERR_FRAUD_HOLD` (HTTP 422).

Shipment atomically produces two artifacts. The first is the order's invoice — exactly one per order — issued `OPEN` with `amount_due_cents` equal to the order's `subtotal_cents`, a `due_date` sixty days after the shipment timestamp (the net-60 terms), and `paid_amount_cents` at zero so that `balance_cents` equals `amount_due_cents`. The second is the order's payout, computed immediately and scheduled: `gross_cents` equals the order's `subtotal_cents` at shipment, the commission rate `commission_bps` is 2,500 basis points when the order is an opening marketplace order (attribution `MARKETPLACE` with `order_seq` equal to 1), 1,500 basis points for any subsequent marketplace order, and zero basis points for any brand-referred order — including a brand-referred opening order. The `commission_cents` is the gross multiplied by the rate in basis points and divided by ten thousand, rounded half-up to whole cents, and `net_cents` is the gross minus the commission. The payout's `scheduled_date` is the shipment timestamp plus the brand's `payout_delay_days`, fixed at computation, and the brand's `payout_balance_cents` is immediately credited by `net_cents`. The payout begins life `SCHEDULED`.

Delivery is a lighter touch: the brand marks a shipped order delivered, moving it `SHIPPED → DELIVERED`; delivering an order in any other status fails with `ERR_INVALID_STATE` (HTTP 409). From `DELIVERED` the order becomes eligible for the returns flow of §3.6. Cancellation is likewise state-gated: cancelling an order not in `PLACED` fails with `ERR_INVALID_STATE` (HTTP 409).

### 3.6. Returns, Invoice Credits, and the Abuse Guard

A retailer requests a return against one of its delivered orders by submitting the `order_id` and a set of `lines`, each pairing an `order_line_id` with a `qty` to send back; the request is validated for shape before any business rule fires — `lines` must be a non-empty array of objects each carrying exactly an `order_line_id` naming an order line that belongs to the referenced order and a positive integer `qty` — and any deviation is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The same fraud gate that guards order placement applies here: a retailer with an `OPEN` fraud flag or a non-`VERIFIED` status is rejected with `ERR_FRAUD_HOLD` (HTTP 422). The request does not check the referenced order's status — the order-state gate fires at brand review time (below) — so an authorization can be requested against an order in any status. The request creates a return authorization in `REQUESTED` together with its return lines — each line carries a `return_auth_id` back to its authorization alongside the `order_line_id` and `qty` — and fixes `is_opening_order` from the referenced order's `order_seq` — true exactly when the order was the opening order for its retailer-brand pair. The new authorization carries `return_fee_cents` and `credit_cents` at zero; both are assigned only when receipt is recorded (below).

Review belongs to the selling brand, acting as itself, and accepts the same decision vocabulary as overall verification: `APPROVE` (or `approve` or `APPROVED`) to approve, `REJECT` (or `reject` or `REJECTED`) to reject; any other value is rejected with `ERR_INVALID_REQUEST`. Rejection is always available and moves the authorization `REQUESTED → REJECTED`. Approval moves it `REQUESTED → APPROVED` but is gated twice: the referenced order must be in `DELIVERED` or `PARTIALLY_RETURNED` — approving against an order in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409) — and the retailer's return rate, evaluated in its provisional form — that is, computed from returns already received before this authorization is processed — must be strictly below 0.20. A retailer at or above that boundary is rejected with `ERR_RETURN_ABUSE_GUARD` (HTTP 422). A review attempted on an authorization no longer `REQUESTED` is rejected with `ERR_INVALID_STATE` (HTTP 409). The provisional nature of this snapshot matters: a retailer sitting just under the threshold can be approved and then cross it with this very return, after which later authorizations are gated on the updated value.

Physical receipt is recorded by a `PlatformAdmin` and is the operation that unwinds the merchandise. Receipt requires the authorization to be `APPROVED` — an authorization in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409) — and the referenced order to be in `DELIVERED` or `PARTIALLY_RETURNED` (any other order status likewise fails with `ERR_INVALID_STATE`, HTTP 409); and it enforces return-quantity integrity: the cumulative received quantity per order line — across this and every earlier received authorization — must never exceed that line's `net_sold_qty`; an overrun is rejected with `ERR_RETURN_QTY_EXCEEDED` (HTTP 422). On a successful receipt, several things happen in one coherent step. Each return line draws down its order line's `net_sold_qty` by the returned `qty`. The return credit is computed in a pinned order: first the returned merchandise value, the sum over the authorization's lines of each returned quantity times its order line's `unit_price_cents`; then the fee, which is zero cents when `is_opening_order` is true and otherwise fifteen percent of the merchandise value rounded half-up to whole cents, computed from the merchandise value and never from the invoice balance; then the raw credit of merchandise minus fee; and finally `credit_cents`, clamped so it never exceeds the invoice's current `amount_due_cents` and never goes below zero (the lazy overdue evaluation of §2.5 is applied to the invoice before the clamp reads `amount_due_cents`; in the degenerate case where the order has no invoice, the raw credit stands with only the lower clamp applied). The authorization's `return_fee_cents` is set to the computed fee and its `credit_cents` to the clamped credit, and it moves to `RECEIVED`. The invoice's `amount_due_cents` is then reduced by `credit_cents` (it too can never fall below zero), `balance_cents` is recomputed, and the invoice's status is re-evaluated — if the balance reaches zero while the invoice is `OPEN` or `OVERDUE`, it flips to `PAID`. The referenced order transitions per its own machine: from `DELIVERED` to `PARTIALLY_RETURNED` when at least one line still has units sold, or to `RETURNED` when every line's `net_sold_qty` has reached zero, and likewise from `PARTIALLY_RETURNED` either staying in `PARTIALLY_RETURNED` or completing to `RETURNED` on the same criterion. The retailer's `return_rate` is then recomputed in its final form — with this authorization's units included in the numerator — and persisted, and the retailer's credit account `available_cents` is recomputed per §3.9.

The `return_rate` itself is a simple ratio maintained across all of the retailer's activity: the numerator is the total units returned across return authorizations that have reached `RECEIVED`, spanning every order; the denominator is the total `net_sold_qty` across all order lines whose order is not `CANCELLED`; when the denominator is zero the rate is zero. The value is stored to four decimal places with round-half-up, and it is recomputed on every unit-affecting mutation — explicitly including order placement (which grows the `net_sold_qty` denominator by the new lines' quantities) and order cancellation (which removes the cancelled order's units from the denominator), in addition to return receipt.

### 3.7. Fraud Screening and Its Cascades

The risk team raises a fraud flag as the `RiskAnalyst` role, naming the `retailer_id`, a `flag_type` of `STRAW_STOREFRONT`, `CONSUMER_RESELLER`, or `RETURN_ABUSE` (any other `flag_type` is rejected with `ERR_INVALID_REQUEST`, HTTP 400), and optionally an `order_id` linking the flag to the order that triggered it (an empty string when no order is involved). A new flag is `OPEN`, and while any flag remains `OPEN` the fraud gate of §3.4 and §3.6 blocks the retailer from placing orders or requesting returns.

Adjudication belongs to `PlatformAdmin`. Dismissal moves the flag `OPEN → DISMISSED` with no further effect. Confirmation moves it `OPEN → CONFIRMED` and fires one of two cascades depending on the flag type; either action on a flag no longer `OPEN` is rejected with `ERR_INVALID_STATE` (HTTP 409). For `STRAW_STOREFRONT` or `CONSUMER_RESELLER`, the linked retailer transitions `VERIFIED → SUSPENDED` (the flag itself is still confirmed when the retailer is in any other status — the suspension simply does not apply); its credit account transitions `ACTIVE → FROZEN` (likewise skipped when the account is absent or not `ACTIVE`); and every one of its orders still `PLACED` is cancelled — and each such cancellation issues a compensating payout to the order's brand, already `PAID`, with a commission of zero basis points so that `net_cents` equals the order's `subtotal_cents`, crediting the brand's `payout_balance_cents` by that amount. Brands whose merchandise was committed against a fraudulent buyer are thus made whole immediately. These cascade cancellations are unit-affecting mutations and recompute the retailer's `return_rate` per §3.6. For `RETURN_ABUSE`, the cascade runs against the brand of the linked order instead — a flag without a linked order applies no assessment at all — and the brand's `abuse_flags` increments by one and its `payout_balance_cents` is debited a flat 5,000 cents per assessment (a debit that may push the balance negative); when `abuse_flags` reaches 5, an `ACTIVE` brand auto-transitions to `SUSPENDED` and stays there until reinstated per §3.2.

### 3.8. Exclusivity Grants and Territory Conflict

A brand may grant a retailer exclusive territory by creating an exclusivity grant as the `Brand` role, supplying the `brand_id`, the protected `retailer_id`, the territory center as `center_lat` and `center_lng`, an optional `radius_km` defaulting to 5 kilometers, and a half-open validity window from `starts_at` (inclusive) to `ends_at` (exclusive). Grant creation is the second OCC-guarded write: the request must carry `expected_brand_version`, and a stale brand version is rejected with `ERR_STALE_VERSION` (HTTP 412); the `starts_at`/`ends_at` window well-formedness and overlap checks below are evaluated only after the OCC check passes. Creating the grant bumps the brand's `version` along with the new grant's own bookkeeping.

The window must be well-formed: `ends_at` must fall after `starts_at`, and no two grants for the same brand and the same retailer may have overlapping half-open intervals while both are `ACTIVE` — intervals that merely touch at an endpoint do not overlap. A malformed or overlapping interval is rejected with `ERR_GRANT_OVERLAP` (HTTP 422). New grants begin `ACTIVE`.

A grant blocks competing order placements when every one of the following holds: the grant's brand is the order's brand; the grant is `ACTIVE` at evaluation time — grants whose `ends_at` has been reached are first flipped to `EXPIRED` by lazy evaluation and no longer block; the logical-clock now falls within the window, at or after `starts_at` and strictly before `ends_at`; the ordering retailer is not the grant's protected retailer; and the great-circle distance between the grant's center and the retailer's storefront `lat`/`lng` — computed with the haversine formula using an earth radius of 6,371.0 kilometers — is strictly less than `radius_km`. A storefront sitting exactly on the boundary circle is not blocked. When any grant satisfies all five conditions, the placement fails with `ERR_TERRITORY_CONFLICT` (HTTP 422).

A brand may revoke its own active grant at any time, moving it `ACTIVE → REVOKED`; revoking a grant not in `ACTIVE` — including one the lazy evaluation of §2.5 has just flipped to `EXPIRED` — is rejected with `ERR_INVALID_STATE` (HTTP 409). `REVOKED` and `EXPIRED` are both terminal.

### 3.9. Collections: Payments, Overdue Invoices, and Write-Offs

The retailer pays down an invoice by recording a payment as the `Retailer` role, supplying an `amount_cents`; the invoice's lazy overdue evaluation (§2.5) is applied first, and only an invoice in `OPEN` or `OVERDUE` accepts payments — paying an invoice in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Payment bounds are enforced strictly: the amount must be positive and must not exceed the invoice's current `balance_cents`; a non-positive or over-large amount is rejected with `ERR_OVERPAYMENT` (HTTP 422). Each accepted payment creates an immutable `Payment` record bound to the invoice through its `invoice_id`, stamped with the logical-clock `paid_at`, increases the invoice's `paid_amount_cents` by the amount, recomputes `balance_cents` as `amount_due_cents` minus `paid_amount_cents`, and recomputes the credit account's `available_cents`. When the balance reaches zero the invoice flips to `PAID` — from `OPEN` or, if payment arrived late, from `OVERDUE`; the lateness of the settling payment is what the underwriting calculation of §3.3 later reads off `paid_at` versus `due_date`.

Lateness itself is clock-driven. When the logical clock has moved past an invoice's `due_date` and a balance remains, the invoice transitions `OPEN → OVERDUE` the next time it is read or written. An `OVERDUE` invoice that the retailer never cures may be written off by a `PlatformAdmin`, but only once the logical clock has reached at least thirty days past the `due_date`; an earlier attempt — or an attempt on an invoice that is not `OVERDUE` — fails with `ERR_WRITE_OFF_TOO_EARLY` (HTTP 422). Write-off moves the invoice `OVERDUE → WRITTEN_OFF`, a terminal state; it recomputes the account's `available_cents` because the balance is no longer outstanding, and it feeds the retailer's `risk_tier` recomputation through the adverse tally of the underwriting calculation. Critically, a write-off never claws back the brand's payout: collection risk on net-60 terms is the platform's, and the brand's `payout_balance_cents` is not debited.

### 3.10. Payout Processing

Payouts are settled by the operations team in three steps. A periodic batch run, invoked by a `PlatformAdmin`, sweeps every payout still `SCHEDULED` whose `scheduled_date` has been reached by the logical clock — processed in the standard ascending `created_at` order — and moves each to `PROCESSING`, debiting each brand's `payout_balance_cents` by that payout's `net_cents` — the debit is recorded even when it takes the balance negative. The payout status enum spans `SCHEDULED`, `PROCESSING`, `PAID`, and `FAILED`, though the fail action as specified returns a payout to `SCHEDULED` for retry rather than parking it in `FAILED`; `PAID` is the only terminal state. A payout in `PROCESSING` is then either completed, moving `PROCESSING → PAID`, or failed, moving `PROCESSING → SCHEDULED` with a compensating credit of `net_cents` to the brand's balance that exactly undoes the earlier debit, so the next batch run retries the payout cleanly; either action on a payout not in `PROCESSING` is rejected with `ERR_INVALID_STATE` (HTTP 409). Because the schedule was fixed at shipment, neither retailer lateness nor invoice write-off disturbs any of these steps — the brand is paid on time regardless.

### 3.11. Browsing and Reverse Reachability

Beyond the workflows above, the platform exposes read access over every collection. Retailers may be listed with optional `verification_status` and `store_type` filters; brands with an optional `onboarding_status` filter; credit accounts with optional `retailer_id` and `status` filters; orders with optional `retailer_id`, `brand_id`, and `status` filters; payouts with optional `brand_id`, `order_id`, and `status` filters; exclusivity grants with optional `brand_id`, `retailer_id`, and `status` filters; and fraud flags with optional `retailer_id`, `order_id`, and `status` filters. An order's lines, its invoice (returned as an array of zero or one entries, since an invoice exists only after shipment), and its return authorizations are each reachable from the order; a return authorization's lines are reachable from the authorization; and the return lines recorded against a specific order line are reachable from that order line, anchoring reverse reachability across the return flow. Payments allocated to an invoice are likewise listed from the invoice. Reading an invoice or a grant applies the lazy time evaluation of §2.5 before responding — including the invoice entries returned through an order's invoice listing. An order line's return-lines listing returns every return line recorded against that order line, across all of its return authorizations and regardless of authorization status. Reads are available to `PlatformAdmin`, `RiskAnalyst`, `Retailer`, and `Brand` as listed in §4, with credit-account and fraud-flag reads restricted to `PlatformAdmin` and `RiskAnalyst`, and payout reads additionally closed to `Retailer`.

## 4. Endpoint Definitions

Operations that create a new resource — registering a retailer, creating a brand, opening a credit account, placing an order, recording a payment, requesting a return authorization, creating an exclusivity grant, or raising a fraud flag — return `201 Created`. Operations that act on an existing resource without creating a new one — verification and document review, activation and reinstatement, limit review, freeze/unfreeze/close, ship/deliver/cancel, write-off, return review and receipt, payout processing, completion and failure, revocation, fraud confirmation and dismissal, and the clock set — return `200 OK`. All list and detail reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | PlatformAdmin |
| POST | `/wholesale/retailers` | Register a retail buyer with storefront proof and resale certificate | Anonymous |
| GET | `/wholesale/retailers` | List retailers with optional filters | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| GET | `/wholesale/retailers/{id}` | Fetch one retailer | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| POST | `/wholesale/retailers/{id}/documents/review` | Confirm or reject one verification document | PlatformAdmin |
| POST | `/wholesale/retailers/{id}/verify` | Overall verification decision | PlatformAdmin |
| POST | `/wholesale/retailers/{id}/request-more-info` | Move a pending retailer to MORE_INFO_REQUESTED | PlatformAdmin |
| POST | `/wholesale/retailers/{id}/verification/resubmit` | Retailer resubmits verification documents | Retailer |
| POST | `/wholesale/brands` | Create a brand in DRAFT with its commercial configuration | Brand |
| GET | `/wholesale/brands` | List brands with optional filters | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| GET | `/wholesale/brands/{id}` | Fetch one brand | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| POST | `/wholesale/brands/{id}/activate` | Activate a fully-configured brand | Brand |
| POST | `/wholesale/brands/{id}/reinstate` | Reinstate a suspended brand | PlatformAdmin |
| POST | `/wholesale/credit-accounts` | Open a credit account for a VERIFIED retailer | PlatformAdmin |
| GET | `/wholesale/credit-accounts` | List credit accounts with optional filters | PlatformAdmin, RiskAnalyst |
| GET | `/wholesale/credit-accounts/{id}` | Fetch one credit account | PlatformAdmin, RiskAnalyst |
| POST | `/wholesale/credit-accounts/{id}/limit-review` | Re-run underwriting and set a new limit (OCC-guarded) | PlatformAdmin |
| POST | `/wholesale/credit-accounts/{id}/unfreeze` | Unfreeze a FROZEN account once the retailer is VERIFIED | PlatformAdmin |
| POST | `/wholesale/credit-accounts/{id}/close` | Close a FROZEN account with no overdue invoices | PlatformAdmin |
| POST | `/wholesale/orders` | Place a wholesale order with line items | Retailer |
| GET | `/wholesale/orders` | List orders with optional filters | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| GET | `/wholesale/orders/{id}` | Fetch one order | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| GET | `/wholesale/orders/{id}/lines` | List an order's lines | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| GET | `/wholesale/orders/{id}/invoice` | Fetch the order's invoice (zero or one) | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| GET | `/wholesale/orders/{id}/return-authorizations` | List return authorizations for the order | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| POST | `/wholesale/orders/{id}/ship` | Ship a placed order; issues invoice and payout | Brand |
| POST | `/wholesale/orders/{id}/deliver` | Mark a shipped order delivered | Brand |
| POST | `/wholesale/orders/{id}/cancel` | Retailer cancels a still-placed order | Retailer |
| GET | `/wholesale/invoices/{id}` | Fetch one invoice (lazy overdue evaluation applied) | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| POST | `/wholesale/invoices/{id}/payments` | Record a retailer payment against an invoice | Retailer |
| GET | `/wholesale/invoices/{id}/payments` | List payments allocated to an invoice | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| POST | `/wholesale/invoices/{id}/write-off` | Write off an overdue invoice at least 30 days past due | PlatformAdmin |
| POST | `/wholesale/return-authorizations` | Request a return authorization against a delivered order | Retailer |
| GET | `/wholesale/return-authorizations/{id}` | Fetch one return authorization | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| GET | `/wholesale/return-authorizations/{id}/lines` | List a return authorization's lines | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| GET | `/wholesale/order-lines/{id}` | Fetch one order line | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| GET | `/wholesale/order-lines/{id}/return-lines` | List return lines recorded against an order line | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| POST | `/wholesale/return-authorizations/{id}/review` | Brand approves or rejects a requested return | Brand |
| POST | `/wholesale/return-authorizations/{id}/receive` | Record physical receipt of an approved return | PlatformAdmin |
| GET | `/wholesale/payouts` | List payouts with optional filters | PlatformAdmin, RiskAnalyst, Brand |
| GET | `/wholesale/payouts/{id}` | Fetch one payout | PlatformAdmin, RiskAnalyst, Brand |
| POST | `/wholesale/payouts/process-due` | Batch-process all due SCHEDULED payouts | PlatformAdmin |
| POST | `/wholesale/payouts/{id}/complete` | Mark a processing payout paid | PlatformAdmin |
| POST | `/wholesale/payouts/{id}/fail` | Fail a processing payout back to SCHEDULED | PlatformAdmin |
| POST | `/wholesale/exclusivity-grants` | Grant a retailer an exclusive territory (OCC-guarded) | Brand |
| GET | `/wholesale/exclusivity-grants` | List grants with optional filters (lazy expiry applied) | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| GET | `/wholesale/exclusivity-grants/{id}` | Fetch one grant | PlatformAdmin, RiskAnalyst, Retailer, Brand |
| POST | `/wholesale/exclusivity-grants/{id}/revoke` | Brand revokes an active grant | Brand |
| POST | `/wholesale/fraud-flags` | Raise a fraud flag on a retailer | RiskAnalyst |
| GET | `/wholesale/fraud-flags` | List fraud flags with optional filters | PlatformAdmin, RiskAnalyst |
| GET | `/wholesale/fraud-flags/{id}` | Fetch one fraud flag | PlatformAdmin, RiskAnalyst |
| POST | `/wholesale/fraud-flags/{id}/confirm` | Confirm an open flag; fires the fraud cascade | PlatformAdmin |
| POST | `/wholesale/fraud-flags/{id}/dismiss` | Dismiss an open flag | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERIFICATION_INCOMPLETE` | 422 |
| `ERR_RESUBMISSION_LIMIT` | 422 |
| `ERR_FRAUD_HOLD` | 422 |
| `ERR_RETURN_ABUSE_GUARD` | 422 |
| `ERR_CASE_PACK_VIOLATION` | 422 |
| `ERR_TERRITORY_CONFLICT` | 422 |
| `ERR_GRANT_OVERLAP` | 422 |
| `ERR_RETURN_QTY_EXCEEDED` | 422 |
| `ERR_MIN_ORDER_VALUE` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_WRITE_OFF_TOO_EARLY` | 422 |
| `ERR_BRAND_SUSPENDED` | 422 |
| `ERR_LEAD_TIME_NOT_MET` | 422 |
